from flask import Flask, jsonify, request # Framework principal
from pymongo import MongoClient # Connexion MongoDB
from bson.objectid import ObjectId # Gestion des IDs MongoDB
from werkzeug.security import generate_password_hash, check_password_hash # Sécurité mots de passe
from datetime import datetime, timedelta # Gestion du temps
import os # Variables d'environnement
import jwt # Authentification Tokens
from functools import wraps # Création de décorateurs
from flask_limiter import Limiter # Protection contre les abus
from flask_limiter.util import get_remote_address # Identification IP
from flask_cors import CORS # Autorisation multi-platefomes
import cloudinary # Stockage Cloud
import cloudinary.uploader # Upload de fichiers

# --- CONFIGURATION CLOUDINARY (Tes identifiants) ---
cloudinary.config( 
  cloud_name = "dpxjchsm9", 
  api_key = "267651223626921", 
  api_secret = "mCzSPc6jPu5N9pTE38REnK48izI", 
  secure = True
)

app = Flask(__name__) # Initialisation Flask
CORS(app) # Activation CORS

# --- CONFIGURATION SERVEUR ---
SECRET_KEY = os.getenv("SECRET_KEY", "ChangeThisSecret") # Clé de signature
MONGO_URI = os.getenv("MONGO_URI") # URL Atlas
app.config["SECRET_KEY"] = SECRET_KEY

# --- PROTECTION ANTI-SPAM ---
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

# --- CONNEXION BASE DE DONNÉES ---
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["AstraDB"]

# Initialisation des collections
users_col = db["users"]
posts_col = db["posts"]
likes_col = db["likes"]
follows_col = db["follows"]
messages_col = db["messages"]
comments_col = db["comments"]
notifications_col = db["notifications"]
friendships_col = db["friendships"]

# --- MIDDLEWARE : VÉRIFICATION DU TOKEN ---
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split(" ")
            if len(parts) == 2: token = parts[1]
        if not token:
            return jsonify({"error": "Token manquant"}), 401
        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            current_user = users_col.find_one({"username": data["username"]})
        except:
            return jsonify({"error": "Token invalide"}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# --- SYSTÈME DE PLANÈTES (GAMIFICATION) ---
def get_planet(score):
    if score < 5: return "🌑 Lune"
    elif score < 20: return "🟠 Mars"
    elif score < 50: return "🔵 Terre"
    elif score < 100: return "🟣 Neptune"
    else: return "☀️ Soleil"

def update_friendship(user1, user2, points):
    relation = friendships_col.find_one({"$or":[{"user1":user1,"user2":user2},{"user1":user2,"user2":user1}]})
    if relation:
        new_score = relation["score"] + points
        friendships_col.update_one({"_id": relation["_id"]},{"$set":{"score":new_score,"planet":get_planet(new_score),"last_interaction":datetime.utcnow()}})
    else:
        # Si compte public, on crée la relation en "accepted" direct
        friendships_col.insert_one({"user1":user1,"user2":user2,"score":points,"planet":get_planet(points),"status":"accepted","last_interaction":datetime.utcnow()})

# --- ROUTES GÉNÉRALES ---

@app.route("/") # Ta page d'accueil navigateur
def home():
    return {"status": " serveur Yrion actif 🚀", "créateur": "Alan Mitha", "version": "3.3"}

@app.route("/utilisateurs", methods=["POST"]) # Inscription avec choix Privé/Public
def creer_utilisateur():
    data = request.json
    if users_col.find_one({"username": data["username"]}): return jsonify({"error":"username déjà utilisé"}),400
    if users_col.find_one({"email": data["email"]}): return jsonify({"error":"email déjà utilisé"}),400
    hashed = generate_password_hash(data["password"])
    user = {
        "username": data["username"],
        "email": data["email"],
        "password": hashed,
        "is_private": data.get("is_private", False), # NOUVEAU : Choix utilisateur
        "bio": "",
        "profile_picture": "",
        "langue": "fr",
        "created_at": datetime.utcnow(),
        "online": False
    }
    users_col.insert_one(user)
    return jsonify({"message":"Utilisateur créé"})

@app.route("/login", methods=["POST"]) # Connexion
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if not user: return jsonify({"error":"Utilisateur introuvable"}),404
    if not check_password_hash(user["password"], data["password"]): return jsonify({"error":"Mot de passe incorrect"}),401
    token = jwt.encode({"username":user["username"],"exp":datetime.utcnow() + timedelta(hours=24)}, app.config["SECRET_KEY"], algorithm="HS256")
    users_col.update_one({"_id":user["_id"]},{"$set":{"online":True}})
    return jsonify({"token":token})

# --- SYSTÈME D'AMITIÉ (DEMANDES) ---

@app.route("/friend-request/send/<target_username>", methods=["POST"]) # Envoyer demande
@token_required
def send_friend_request(current_user, target_username):
    if current_user["username"] == target_username: return jsonify({"error": "Auto-ajout impossible"}), 400
    existing = friendships_col.find_one({"$or": [{"user1": current_user["username"], "user2": target_username}, {"user1": target_username, "user2": current_user["username"]}]})
    if existing: return jsonify({"message": "Déjà en relation"}), 400
    friendships_col.insert_one({"user1": current_user["username"], "user2": target_username, "status": "pending", "score": 0, "planet": "🌑 Lune", "created_at": datetime.utcnow()})
    return jsonify({"message": f"Demande envoyée à {target_username}"})

@app.route("/friend-request/accept/<sender_username>", methods=["POST"]) # Accepter demande
@token_required
def accept_friend(current_user, sender_username):
    result = friendships_col.update_one({"user1": sender_username, "user2": current_user["username"], "status": "pending"}, {"$set": {"status": "accepted"}})
    if result.modified_count == 0: return jsonify({"error": "Demande introuvable"}), 404
    return jsonify({"message": "Ami ajouté !"})

# --- MESSAGERIE (AVEC PROTECTION PRIVÉ) ---

@app.route("/message", methods=["POST"])
@token_required
def message(current_user):
    data = request.json
    receiver = users_col.find_one({"username": data["receiver"]})
    if not receiver: return jsonify({"error": "Destinataire introuvable"}), 404

    # PROTECTION : Si privé, vérifier amitié acceptée
    if receiver.get("is_private", False):
        is_friend = friendships_col.find_one({"status": "accepted", "$or": [{"user1": current_user["username"], "user2": data["receiver"]}, {"user1": data["receiver"], "user2": current_user["username"]}]})
        if not is_friend: return jsonify({"error": "Compte privé : Amis seulement"}), 403

    msg = {"sender": current_user["username"], "receiver": data["receiver"], "content": data["content"], "date": datetime.utcnow()}
    messages_col.insert_one(msg)
    update_friendship(current_user["username"], data["receiver"], 3)
    return jsonify({"message": "Signal envoyé !"})

@app.route("/messages/<contact>")
@token_required
def get_messages(current_user, contact):
    query = {"$or": [{"sender": current_user["username"], "receiver": contact}, {"sender": contact, "receiver": current_user["username"]}]}
    msgs = messages_col.find(query).sort("date", 1)
    return jsonify([{"sender": m["sender"], "content": m["content"], "date": m["date"].isoformat()} for m in msgs])

# --- VIDÉOS (REMISES EN PLACE) ---

@app.route("/videos/liste", methods=["GET"])
def liste_videos():
    videos = posts_col.find({"type": "video"}).sort("date", -1)
    return jsonify([{"id": str(v["_id"]), "username": v["username"], "url": v["video_url"], "description": v.get("content", "")} for v in videos])

@app.route("/post/video", methods=["POST"])
@token_required
def upload_video(current_user):
    if 'file' not in request.files: return jsonify({"error": "Aucune vidéo"}), 400
    video_file = request.files['file']
    description = request.form.get("content", "Nouvelle vidéo Astra 🚀")
    try:
        upload_result = cloudinary.uploader.upload(video_file, resource_type="video", folder="astra_videos/")
        new_video_post = {"username": current_user["username"], "content": description, "video_url": upload_result["secure_url"], "type": "video", "date": datetime.utcnow(), "likes": 0}
        posts_col.insert_one(new_video_post)
        return jsonify({"message": "Vidéo publiée !", "url": upload_result["secure_url"]})
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- PROFIL & AVATAR (COMPLET) ---

@app.route("/profil/<username>") # Voir profil avec filtres de confidentialité
def profil_public(username):
    user = users_col.find_one({"username": username})
    if not user: return jsonify({"error": "Utilisateur introuvable"}), 404
    
    is_private = user.get("is_private", False)
    followers = follows_col.count_documents({"followed": username})
    following = follows_col.count_documents({"follower": username})
    posts_count = posts_col.count_documents({"username": username})

    res = {"username": username, "profile_picture": user.get("profile_picture", ""), "online": user.get("online", False), "is_private": is_private}

    if not is_private: # On ne montre la bio/stats que si c'est public
        res.update({"bio": user.get("bio", ""), "followers": followers, "following": following, "posts": posts_count})
    
    return jsonify(res)

@app.route("/utilisateurs/avatar", methods=["POST"]) # Upload de l'avatar (Cloudinary)
@token_required
def upload_avatar(current_user):
    if 'file' not in request.files: return jsonify({"error": "Aucun fichier"}), 400
    try:
        upload_result = cloudinary.uploader.upload(request.files['file'], folder="astra_avatars/", public_id=f"user_{current_user['username']}", overwrite=True)
        image_url = upload_result["secure_url"]
        users_col.update_one({"_id": current_user["_id"]}, {"$set": {"profile_picture": image_url}})
        return jsonify({"message": "Avatar mis à jour !", "url": image_url})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/logout", methods=["POST"])
@token_required
def logout(current_user):
    users_col.update_one({"_id": current_user["_id"]}, {"$set": {"online": False}})
    return jsonify({"message": "Déconnexion réussie"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
