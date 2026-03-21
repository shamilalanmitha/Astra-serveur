from flask import Flask, jsonify, request
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta 
import os
import jwt
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import cloudinary
import cloudinary.uploader

# Configuration Cloudinary
cloudinary.config( 
  cloud_name = "dpxjchsm9", 
  api_key = "267651223626921", 
  api_secret = "mCzSPc6jPu5N9pTE38REnK48izI", 
  secure = True
)

app = Flask(__name__)
CORS(app)

# ----- CONFIG -----
SECRET_KEY = os.getenv("SECRET_KEY", "ChangeThisSecret")
MONGO_URI = os.getenv("MONGO_URI")
app.config["SECRET_KEY"] = SECRET_KEY

# ----- RATE LIMIT -----
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

# ----- DATABASE -----
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["AstraDB"]

try:
    client.admin.command('ping')
    print("✅ MongoDB Atlas : Connexion réussie !")
except Exception as e:
    print(f"❌ Erreur de connexion MongoDB : {e}")

users_col = db["users"]
posts_col = db["posts"]
likes_col = db["likes"]
follows_col = db["follows"]
messages_col = db["messages"]
comments_col = db["comments"]
notifications_col = db["notifications"]
friendships_col = db["friendships"]

# ----- TOKEN MIDDLEWARE -----
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

# ----- PLANET SYSTEM -----
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
        friendships_col.insert_one({"user1":user1,"user2":user2,"score":points,"planet":get_planet(points),"last_interaction":datetime.utcnow()})

# ----- ROUTES -----

@app.route("/")
def home():
    return {"status": "Astra serveur actif 🚀", "créateur": "Alan Mitha", "version": "3.1"}

@app.route("/utilisateurs", methods=["POST"])
def creer_utilisateur():
    data = request.json
    if users_col.find_one({"username": data["username"]}): return jsonify({"error":"username déjà utilisé"}),400
    if users_col.find_one({"email": data["email"]}): return jsonify({"error":"email déjà utilisé"}),400
    hashed = generate_password_hash(data["password"])
    user = {"username":data["username"],"email":data["email"],"password":hashed,"bio":"","profile_picture":"","langue":"fr","created_at":datetime.utcnow(),"online":False}
    users_col.insert_one(user)
    return jsonify({"message":"Utilisateur créé"})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if not user: return jsonify({"error":"Utilisateur introuvable"}),404
    if not check_password_hash(user["password"], data["password"]): return jsonify({"error":"Mot de passe incorrect"}),401
    token = jwt.encode({"username":user["username"],"exp":datetime.utcnow() + timedelta(hours=24)}, app.config["SECRET_KEY"], algorithm="HS256")
    users_col.update_one({"_id":user["_id"]},{"$set":{"online":True}})
    return jsonify({"token":token})

# ----- MESSAGES -----

@app.route("/message", methods=["POST"])
@token_required
def message(current_user):
    data = request.json
    msg = {"sender": current_user["username"], "receiver": data["receiver"], "content": data["content"], "date": datetime.utcnow()}
    messages_col.insert_one(msg)
    update_friendship(current_user["username"], data["receiver"], 3)
    return jsonify({"message": "Signal envoyé !"})

@app.route("/messages/<contact>")
@token_required
def get_messages(current_user, contact):
    query = {"$or": [{"sender": current_user["username"], "receiver": contact}, {"sender": contact, "receiver": current_user["username"]}]}
    msgs = messages_col.find(query).sort("date", 1) # Ordre chronologique
    output = []
    for m in msgs:
        output.append({"sender": m["sender"], "content": m["content"], "date": m["date"].isoformat()})
    return jsonify(output)

# ----- VIDEOS -----

@app.route("/videos/liste", methods=["GET"])
def liste_videos():
    videos = posts_col.find({"type": "video"}).sort("date", -1)
    output = []
    for v in videos:
        output.append({"id": str(v["_id"]), "username": v["username"], "url": v["video_url"], "description": v.get("content", "")})
    return jsonify(output)

@app.route("/post/video", methods=["POST"])
@token_required
def upload_video(current_user):
    if 'file' not in request.files: return jsonify({"error": "Aucune vidéo"}), 400
    video_file = request.files['file']
    description = request.form.get("content", "Nouvelle vidéo Astra 🚀")
    try:
        upload_result = cloudinary.uploader.upload(video_file, resource_type = "video", folder = "astra_videos/", chunk_size = 6000000)
        video_url = upload_result["secure_url"]
        new_video_post = {"username": current_user["username"], "content": description, "video_url": video_url, "type": "video", "date": datetime.utcnow(), "likes": 0}
        posts_col.insert_one(new_video_post)
        return jsonify({"message": "Vidéo publiée !", "url": video_url})
    except Exception as e: return jsonify({"error": str(e)}), 500

# ----- UTILISATEURS & PROFIL -----

@app.route("/utilisateurs/liste")
@token_required
def liste_utilisateurs(current_user):
    users = users_col.find({"username": {"$ne": current_user["username"]}})
    output = []
    for u in users:
        output.append({"username": u["username"], "online": u.get("online", False), "avatar": u.get("profile_picture", "")})
    return jsonify(output)

@app.route("/profil/<username>")
def profil_public(username):
    user = users_col.find_one({"username": username})
    if not user: return jsonify({"error": "Utilisateur introuvable"}), 404
    followers = follows_col.count_documents({"followed": username})
    following = follows_col.count_documents({"follower": username})
    posts_count = posts_col.count_documents({"username": username})
    return jsonify({"username": username, "bio": user.get("bio", ""), "profile_picture": user.get("profile_picture", ""), "followers": followers, "following": following, "posts": posts_count, "online": user.get("online", False)})

@app.route("/utilisateurs/me", methods=["GET"])
@token_required
def get_my_profile(current_user):
    followers = follows_col.count_documents({"followed": current_user["username"]})
    following = follows_col.count_documents({"follower": current_user["username"]})
    posts_count = posts_col.count_documents({"username": current_user["username"]})
    return jsonify({"_id": str(current_user["_id"]), "username": current_user["username"], "email": current_user["email"], "bio": current_user.get("bio", ""), "profile_picture": current_user.get("profile_picture", ""), "followers": followers, "following": following, "posts": posts_count})

@app.route("/utilisateurs/avatar", methods=["POST"])
@token_required
def upload_avatar(current_user):
    if 'file' not in request.files: return jsonify({"error": "Aucun fichier"}), 400
    try:
        upload_result = cloudinary.uploader.upload(request.files['file'], folder="astra_avatars/", public_id=f"user_{current_user['username']}", overwrite=True, transformation=[{"width": 400, "height": 400, "crop": "fill", "gravity": "face"}, {"radius": "max"}])
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
