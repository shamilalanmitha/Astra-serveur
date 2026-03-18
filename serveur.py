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

# Remplace par tes clés que tu as trouvées tout à l'heure
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

# AJOUTE CE TEST ICI :
try:
    client.admin.command('ping')
    print("✅ MongoDB Atlas : Connexion réussie !")
except Exception as e:
    print(f"❌ Erreur de connexion MongoDB : {e}")

users_col = db["users"]
# ... reste de tes collections
users_col = db["users"]
posts_col = db["posts"]
likes_col = db["likes"]
follows_col = db["follows"]
messages_col = db["messages"]
comments_col = db["comments"]
notifications_col = db["notifications"]
friendships_col = db["friendships"]

# ----- LANGUAGES -----
LANGUAGES = [
    {"code": "fr", "name": "Français"},
    {"code": "en", "name": "English"},
    {"code": "mg", "name": "Malagasy"}
]

# ----- TOKEN -----
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if "Authorization" in request.headers:
            parts = request.headers["Authorization"].split(" ")
            if len(parts) == 2:
                token = parts[1]

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
    if score < 5:
        return "🌑 Lune"
    elif score < 20:
        return "🟠 Mars"
    elif score < 50:
        return "🔵 Terre"
    elif score < 100:
        return "🟣 Neptune"
    else:
        return "☀️ Soleil"


def update_friendship(user1, user2, points):

    relation = friendships_col.find_one({
        "$or":[
            {"user1":user1,"user2":user2},
            {"user1":user2,"user2":user1}
        ]
    })

    if relation:

        new_score = relation["score"] + points

        friendships_col.update_one(
            {"_id": relation["_id"]},
            {
                "$set":{
                    "score":new_score,
                    "planet":get_planet(new_score),
                    "last_interaction":datetime.utcnow()
                }
            }
        )

    else:

        friendships_col.insert_one({
            "user1":user1,
            "user2":user2,
            "score":points,
            "planet":get_planet(points),
            "last_interaction":datetime.utcnow()
        })

    # ----- HOME -----
@app.route("/")
def home():
    return {
        "status": "Astra serveur actif 🚀",
        "créateur": "Alan Mitha",
        "version": "2.1"
    }

# ----- CREATE USER -----
@app.route("/utilisateurs", methods=["POST"])
def creer_utilisateur():

    data = request.json

    if users_col.find_one({"username": data["username"]}):
        return jsonify({"error":"username déjà utilisé"}),400

    if users_col.find_one({"email": data["email"]}):
        return jsonify({"error":"email déjà utilisé"}),400

    hashed = generate_password_hash(data["password"])

    user = {
        "username":data["username"],
        "email":data["email"],
        "password":hashed,
        "bio":"",
        "profile_picture":"",
        "langue":"fr",
        "created_at":datetime.utcnow(),
        "online":False
    }

    users_col.insert_one(user)

    return jsonify({"message":"Utilisateur créé"})


# ----- LOGIN -----
@app.route("/login", methods=["POST"])
def login():

    data = request.json

    user = users_col.find_one({"username": data["username"]})

    if not user:
        return jsonify({"error":"Utilisateur introuvable"}),404

    if not check_password_hash(user["password"], data["password"]):
        return jsonify({"error":"Mot de passe incorrect"}),401

    token = jwt.encode(
        {
            "username":user["username"],
            "exp":datetime.utcnow() + timedelta(hours=24)
        },
        app.config["SECRET_KEY"],
        algorithm="HS256"
    )

    users_col.update_one(
        {"_id":user["_id"]},
        {"$set":{"online":True}}
    )

    return jsonify({"token":token})


# ----- POSTS -----
@app.route("/post", methods=["POST"])
@token_required
@limiter.limit("10/minute")
def creer_post(current_user):

    data = request.json

    post = {
        "content":data["content"],
        "username":current_user["username"],
        "date":datetime.utcnow()
    }

    result = posts_col.insert_one(post)

    return jsonify({
        "message":"Post créé",
        "post_id":str(result.inserted_id)
    })


# ----- GET POSTS -----
@app.route("/posts")
def get_posts():

    posts = posts_col.find().sort("date",-1)

    output = []

    for p in posts:

        likes = likes_col.count_documents({
            "post_id":str(p["_id"])
        })

        output.append({
            "id":str(p["_id"]),
            "content":p["content"],
            "author":p["username"],
            "likes":likes
        })

    return jsonify(output)


# ----- LIKE -----
@app.route("/like", methods=["POST"])
@token_required
def like(current_user):

    data = request.json
    post_id = data["post_id"]

    if likes_col.find_one({
        "username":current_user["username"],
        "post_id":post_id
    }):
        return jsonify({"message":"Déjà liké"}),400

    likes_col.insert_one({
        "username":current_user["username"],
        "post_id":post_id,
        "date":datetime.utcnow()
    })

    post = posts_col.find_one({"_id":ObjectId(post_id)})

    if post:

        update_friendship(
            current_user["username"],
            post["username"],
            1
        )

        notifications_col.insert_one({
            "type":"like",
            "from":current_user["username"],
            "to":post["username"],
            "post_id":post_id,
            "date":datetime.utcnow()
        })

    return jsonify({"message":"Like ajouté"})


# ----- COMMENT -----
@app.route("/comment", methods=["POST"])
@token_required
def comment(current_user):

    data = request.json

    comment = {
        "post_id":data["post_id"],
        "username":current_user["username"],
        "content":data["content"],
        "date":datetime.utcnow()
    }

    comments_col.insert_one(comment)

    return jsonify({"message":"Commentaire ajouté"})


# ----- MESSAGES -----
@app.route("/message", methods=["POST"])
@token_required
def message(current_user):

    data = request.json

    msg = {
        "sender":current_user["username"],
        "receiver":data["receiver"],
        "content":data["content"],
        "date":datetime.utcnow()
    }

    messages_col.insert_one(msg)

    update_friendship(
        current_user["username"],
        data["receiver"],
        3
    )

    return jsonify({"message":"Message envoyé"})

# ----- GET ALL USERS (Pour la barre de stories) -----
@app.route("/utilisateurs/liste")
@token_required
def liste_utilisateurs(current_user):
    # On récupère tous les utilisateurs sauf nous-même
    users = users_col.find({"username": {"$ne": current_user["username"]}})
    
    output = []
    for u in users:
        output.append({
            "username": u["username"],
            "online": u.get("online", False),
            "avatar": u.get("profile_picture", "") # Utile pour les cercles !
        })
    return jsonify(output)

# ----- SEARCH USER -----
@app.route("/search")
def search():
    username = request.args.get("username","")
    users = users_col.find({"username":{"$regex":username, "$options":"i"}})

    output = []
    for u in users:
        # On crée l'icône ici : lune si en ligne, rien si hors ligne
        is_online = u.get("online", False)
        lune = "🌕" if is_online else "" 

        output.append({
            "username": u["username"],
            "online": is_online,
            "status_icon": lune # On envoie la lune directement
        })
    return jsonify(output)

# ----- PROFILE -----
@app.route("/profil/<username>")
def profil(username):

    user = users_col.find_one({"username":username})

    if not user:
        return jsonify({"error":"Utilisateur introuvable"}),404

    followers = follows_col.count_documents({"followed":username})
    following = follows_col.count_documents({"follower":username})
    posts = posts_col.count_documents({"username":username})

    return jsonify({
        "username":username,
        "bio":user.get("bio",""),
        "followers":followers,
        "following":following,
        "posts":posts
    })

# ----- GET MESSAGES (Pour voir la discussion) -----
@app.route("/messages/<contact>")
@token_required
def get_messages(current_user, contact):
    # Récupère les messages entre moi et mon ami
    query = {
        "$or": [
            {"sender": current_user["username"], "receiver": contact},
            {"sender": contact, "receiver": current_user["username"]}
        ]
    }
    msgs = messages_col.find(query).sort("date", 1) # 1 pour l'ordre chronologiques
    
    output = []
    for m in msgs:
        output.append({
            "sender": m["sender"],
            "content": m["content"],
            "date": m["date"].isoformat()
        })
    return jsonify(output)

# ----- VOIR MON PROPRE PROFIL (SÉCURISÉ) -----
@app.route("/utilisateurs/me", methods=["GET"])
@token_required
def get_my_profile(current_user):
    # On compte ses stats en temps réel
    followers = follows_col.count_documents({"followed": current_user["username"]})
    following = follows_col.count_documents({"follower": current_user["username"]})
    posts_count = posts_col.count_documents({"username": current_user["username"]})

    return jsonify({
        "_id": str(current_user["_id"]),
        "username": current_user["username"],
        "email": current_user["email"],
        "bio": current_user.get("bio", "Explorateur de la galaxie Astra"),
        "profile_picture": current_user.get("profile_picture", ""),
        "followers": followers,
        "following": following,
        "posts": posts_count,
        "created_at": current_user.get("created_at").isoformat() if current_user.get("created_at") else None
    })

# ----- METTRE À JOUR LE PROFIL -----
@app.route("/utilisateurs/update", methods=["PUT"])
@token_required
def update_profile(current_user):
    data = request.json
    updates = {}

    # On ne met à jour que ce qui est envoyé
    if "bio" in data:
        updates["bio"] = data["bio"]
    if "profile_picture" in data:
        updates["profile_picture"] = data["profile_picture"]
    
    if not updates:
        return jsonify({"error": "Aucune donnée à modifier"}), 400

    users_col.update_one(
        {"_id": current_user["_id"]},
        {"$set": updates}
    )

    return jsonify({"message": "Profil mis à jour avec succès ✨"})

    # ----- LOGOUT -----statue e ligne deconecter
@app.route("/logout", methods=["POST"])
@token_required
def logout(current_user):
    users_col.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"online": False}}
    )
    return jsonify({"message": "Déconnexion réussie"})

    # ----- PROFIL PUBLIC AMÉLIORÉ -----les utlilisateur peut voir la photo de leur amis---------
@app.route("/profil/<username>")
def profil_public(username):
    user = users_col.find_one({"username": username})

    if not user:
        return jsonify({"error": "Utilisateur introuvable"}), 404

    followers = follows_col.count_documents({"followed": username})
    following = follows_col.count_documents({"follower": username})
    posts_count = posts_col.count_documents({"username": username})

    return jsonify({
        "username": username,
        "bio": user.get("bio", ""),
        "profile_picture": user.get("profile_picture", ""),
        "followers": followers,
        "following": following,
        "posts": posts_count,
        "online": user.get("online", False)
    })

#-----route pour recevoir les photo de mes utilesateur (stoker derectemrent dans cloudinary)---------
@app.route("/utilisateurs/avatar", methods=["POST"])
@token_required
def upload_avatar(current_user):
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier envoyé"}), 400
    
    file_to_upload = request.files['file']
    
    try:
        # 1. Envoi vers Cloudinary avec transformation automatique
        upload_result = cloudinary.uploader.upload(
            file_to_upload,
            folder="astra_avatars/",
            public_id=f"user_{current_user['username']}",
            overwrite=True,
            transformation=[
                {"width": 400, "height": 400, "crop": "fill", "gravity": "face"},
                {"radius": "max"},
                {"fetch_format": "auto"}
            ]
        )
        
        # 2. On récupère l'URL permanente
        image_url = upload_result["secure_url"]

        # 3. On met à jour MongoDB
        users_col.update_one(
            {"_id": current_user["_id"]},
            {"$set": {"profile_picture": image_url}}
        )

        return jsonify({
            "message": "Avatar Astra mis à jour ! 🚀",
            "url": image_url
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----- RUN SERVER (RENDER) -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

