from getpass import getpass
from instagrapi import Client
import time, random

# Configurações
USERNAME = input("Seu usuário: ")
PASSWORD = getpass("Sua senha: ")

# Nome de usuário da conta que você quer pegar os seguidores
TARGET_USERNAME = input("Digite o nome de usuário da conta alvo: ")

# Inicializar o cliente
cl = Client()

def get_followers_of_target():
    print(f"Obtendo lista de seguidores de {TARGET_USERNAME}...")
    user_id = cl.user_id_from_username(TARGET_USERNAME)  # Obtém o ID do usuário alvo
    time.sleep(10)
    followers = cl.user_following(user_id)  # Obtém seguidores da conta alvo
    return followers

# Função para salvar seguidores em um arquivo .txt
def save_followers_to_txt(followers):
    with open("seguidores.txt", "w") as file:
        for user_id, user_info in followers.items():
            time.sleep(3)
            file.write(f"{user_info.username}\n")
    print("Lista de seguidores salva no arquivo 'seguidores.txt'.")

# Função para enviar mensagens
def send_messages(users, mensagem):
    sent_users = set()  # Armazenar usuários que já receberam mensagem
    
    for user_id, user_info in users.items():
        if user_id in sent_users:
            continue  # Pular se já enviou mensagem
        
        try:
            print(f"Enviando mensagem para {user_info.username}...")
            cl.direct_send(mensagem, user_ids=[user_id])
            sent_users.add(user_id)  # Marcar como enviado
            time.sleep(random.uniform(15, 30))  # Intervalo aleatório para evitar bloqueio
        except Exception as e:
            print(f"Erro ao enviar mensagem para {user_info.username}: {e}")
            time.sleep(60)  # Esperar após erro

# Mensagem personalizada
mensagem = "Olá! Obrigado por me seguir. 😊"

# Executar
try:
    followers = get_followers_of_target()
    save_followers_to_txt(followers)  # Salva seguidores no arquivo
    #send_messages(followers, mensagem)  # Envia mensagens para os seguidores
    print("Mensagens enviadas com sucesso!")
except Exception as e:
    print(f"Erro crítico: {e}")
finally:
    cl.logout()
