from collections import defaultdict
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from instagrapi import Client, exceptions
from instagrapi.exceptions import LoginRequired
import time, random, os, logging
from dotenv import load_dotenv
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson import ObjectId


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")  
client = MongoClient(MONGO_URI)
db = client["instaapp"]

users_collection = db["users"]
logs_collection = db["logs"]
envios_collection = db["envios"]
logins_collection = db["logins"]
historico_collection = db['historico']

# Função para registrar histórico
def registrar_historico(tipo_acao, descricao, usuario):
    # Criar o documento com as informações do processo
    historico = {
        "tipo_acao": tipo_acao,
        "descricao": descricao,
        "usuario": usuario,
        "data_hora": datetime.now()
    }
    
    # Inserir o documento na coleção 'historico'
    historico_collection.insert_one(historico)

# Função para registrar login
def registrar_login(username):
    registrar_historico("login", f"Usuário {username} fez login.", username)

# Função para registrar envio de mensagem
def registrar_envio_mensagem(usuario, num_amigos, tipo_envio):
    descricao = f"Envio de mensagem para {num_amigos} usuários. Tipo de envio: {tipo_envio}."
    registrar_historico("envio_mensagem", descricao, usuario)

# Função para registrar erro
def registrar_erro(usuario, mensagem_erro):
    descricao = f"Erro: {mensagem_erro}"
    registrar_historico("erro", descricao, usuario)

def format_envio(envio):
    return {
        "id": str(envio["_id"]),
        "sender": envio.get("sender"),
        "receiver_id": envio.get("receiver_id"),
        "message": envio.get("message"),
        "media": envio.get("media"),
        "timestamp": envio.get("timestamp").isoformat(),
        "tipo_envio": envio.get("tipo_envio"),
        "target_user": envio.get("target_user"),
    }

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

UPLOAD_FOLDER = "uploads"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

LIMITE_AMIGOS = 1000

cl = Client()

# Helpers
def get_users(tipo, target_user=None):
    try:
        if target_user:  # Se tiver target_user, usa ele
            target_id = cl.user_id_from_username(target_user)
        else:  # Senão, usa o próprio usuário logado
            target_id = cl.user_id

        if tipo == "seguidores":
            return cl.user_followers(target_id)
        elif tipo == "seguindo":
            return cl.user_following(target_id)
        else:
            return {
                **cl.user_followers(target_id),
                **cl.user_following(target_id)
            }
            
    except Exception as e:
        logger.error(f"Erro ao buscar usuários: {e}")
        return {}
    return {}

# Rotas
@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))

    # Verifica se a sessão com o Instagram ainda está ativa
    try:
        cl.account_info()  # Isso levanta LoginRequired se não estiver logado
    except LoginRequired:
        session.clear()
        return redirect(url_for("login_page"))

    return redirect(url_for("send_page"))

@app.route("/login", methods=["GET", "POST"])
def login_page():
    # Se o usuário já estiver logado, redireciona para o dashboard
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        
        try:
            cl.login(username, password)
          
            logins_collection.insert_one({
                "username": username,
                "timestamp": datetime.utcnow()
            })
            # Salvar ou atualizar o usuário no Mongo
            users_collection.update_one(
                {"username": username},
                {
                    "$set": {
                        "username": username,
                        "last_login": time.time()
                    }
                },
                upsert=True
            )
            registrar_historico("login", f"Usuário {username} fez login.", username)

            


            session["logged_in"] = True
            return jsonify({"status": "success", "redirect": url_for("dashboard")})
        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({"status": "error", "message": "Credenciais inválidas!"}), 401
    return render_template("index.html")

@app.route("/send")
def send_page():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))

    try:
        user = cl.account_info()
        return render_template("send.html", username=user.username)
    except LoginRequired:
        session.clear()
        return redirect(url_for("login_page"))
  
@app.route("/send-message", methods=["POST"])
def send_message():
    if not session.get("logged_in"):
        return jsonify({"status": "error", "message": "Não autorizado!"}), 401

    try:
        data = {
            "file": request.files.get("media_file"),
            "message": request.form["message"],
            "target_user": request.form.get("target_user", ""),
            "tipo_envio": request.form["tipo_envio"],
            "num_amigos": int(request.form["num_amigos"]),
            "tempo_envio": int(request.form["tempo_envio"])
        }

        if data["num_amigos"] > LIMITE_AMIGOS:
            return jsonify({"status": "error", "message": f"Limite máximo é {LIMITE_AMIGOS}!"}), 400

        users = get_users(data["tipo_envio"], data["target_user"])
        selected_users = random.sample(list(users.keys()), min(data["num_amigos"], len(users)))

        file_path = None
        if data["file"] and data["file"].filename:
            file_path = os.path.join(UPLOAD_FOLDER, data["file"].filename)
            data["file"].save(file_path)    

        for user_id in selected_users:
            try:
                if file_path:
                    if file_path.lower().endswith((".jpg", ".jpeg", ".png")):
                        cl.direct_send_photo(file_path, user_ids=[user_id])
                    elif file_path.lower().endswith((".mp4", ".mov")):
                        cl.direct_send_video(file_path, user_ids=[user_id])
                
                cl.direct_send(data["message"], user_ids=[user_id])

                # Registro no banco
                envios_collection.insert_one({
                    "sender": cl.username,
                    "receiver_id": user_id,
                    "message": data["message"],
                    "media": os.path.basename(file_path) if file_path else None,
                    "timestamp": datetime.utcnow(),
                    "tipo_envio": data["tipo_envio"],
                    "target_user": data.get("target_user", "")
                })
                time.sleep(data["tempo_envio"] * 60)
            
            except exceptions.LoginRequired:
                logger.error("Login requerido, sessão expirada.")
                session.clear()
                return jsonify({"status": "login_required", "redirect": url_for("login_page")}), 401
            except Exception as e:
                logger.error(f"Erro no envio: {e}")
                time.sleep(120)

        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            
        logs_collection.insert_one({
            "username": cl.username,
            "target_user": data["target_user"],
            "tipo_envio": data["tipo_envio"],
            "mensagem": data["message"],
            "num_envios": len(selected_users),
            "tempo_envio": data["tempo_envio"],
            "timestamp": time.time(),
        })

        registrar_envio_mensagem(cl.username, len(selected_users), data["tipo_envio"])  # Registra o envio no histórico


        return jsonify({"status": "success", "message": f"Mensagens enviadas para {len(selected_users)} usuários!"})

    except Exception as e:
        logger.error(f"Erro geral: {e}")
        registrar_erro(cl.username, str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/logs")
def logs():
    if not session.get("logged_in"):
        return redirect(url_for("login_page"))

    user_logs = list(logs_collection.find({"username": cl.username}).sort("timestamp", -1))
    for log in user_logs:
        log["_id"] = str(log["_id"])  # Para evitar erro de serialização
    return jsonify(user_logs)

@app.route("/dashboard", methods=["GET"])
def dashboard():

    if not session.get("logged_in"):
        return redirect(url_for("login_page"))

    try:    
        # Total de envios
        total_envios = envios_collection.count_documents({})

        # Top 5 usuários (agrupa por receiver_id e conta os envios)
        top_usuarios_cursor = envios_collection.aggregate([
            {"$group": {"_id": "$receiver_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ])
        top_usuarios_list = [{"receiver_id": u["_id"], "count": u["count"]} for u in top_usuarios_cursor]

        # Últimos 10 envios (ordenados pela data decrescente)
        ultimos_envios_cursor = envios_collection.find().sort("timestamp", -1).limit(10)
        ultimos_envios = [format_envio(e) for e in ultimos_envios_cursor]

        # Total por tipo de envio
        por_tipo_cursor = envios_collection.aggregate([
            {"$group": {"_id": "$tipo_envio", "count": {"$sum": 1}}}
        ])
        por_tipo_envio = {item["_id"]: item["count"] for item in por_tipo_cursor}

        # Envios por dia (últimos 7 dias)
        sete_dias_atras = datetime.utcnow() - timedelta(days=7)
        por_dia_cursor = envios_collection.aggregate([
            {"$match": {"timestamp": {"$gte": sete_dias_atras}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ])
        envios_por_dia = {item["_id"]: item["count"] for item in por_dia_cursor}

        # Média por hora do dia (calculando a média semanal para cada hora)
        total_por_hora = defaultdict(int)
        # Percorre todos os envios (para produção, pode limitar o range ou usar outra consulta)
        for envio in envios_collection.find():
            if envio.get("timestamp"):
                hora = envio["timestamp"].hour
                total_por_hora[hora] += 1

        media_por_hora = {str(h): round(total_por_hora[h] / 7, 2) for h in range(24)}

        # Renderiza o template 'dashboard.html' passando os dados
        return render_template(
            "dashboard.html",
            total_envios=total_envios,
            top_usuarios=top_usuarios_list,
            ultimos_envios=ultimos_envios,
            por_tipo_envio=por_tipo_envio,
            envios_por_dia=envios_por_dia,
            media_por_hora=media_por_hora
        )
        
    except LoginRequired:
        session.clear()
        return redirect(url_for("login_page"))
    
# Painel Administrativo
@app.route("/admin")
def admin_panel():
    # Verifica se o usuário está logado e é admin
    if not session.get("logged_in") or not session.get("is_admin"):
        return redirect(url_for("login_page"))
    return render_template("admin.html")

@app.route("/api/historico")
def historico_api():
    logs = list(historico_collection.find().sort("data_hora", -1))
    for log in logs:
        log["_id"] = str(log["_id"])
        log["data_hora"] = log["data_hora"].isoformat()
    return jsonify(logs)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

if __name__ == "__main__":
    app.run( port=5001, debug=True)