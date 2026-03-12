from flask import Flask, jsonify, request
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import jwt
from functools import wraps
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# ----- CONFIGURATION SECURE -----
SECRET_KEY = os.getenv("SECRET_KEY", "ChangeThisSecret")
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://AlanMitha:252627shamilmitha02@cluster0.epdfpxp.mongodb.net/?retryWrites=true&w=majority"
app.config["SECRET_KEY"] = SECRET_KEY

# ----- RATE LIMIT -----
limiter = Limiter(app, key_func=get_remote_address)

# ----- DATABASE -----
client = MongoClient(MONGO_URI)
db = client["AstraDB"]

users_col = db["users"]
posts_col = db["posts"]
likes_col = db["likes"]
follows_col = db["follows"]
messages_col = db["messages"]
comments_col = db["comments"]
notifications_col = db["notifications"]
friendships_col = db["friendships"]

# ----- LANGUES -----
LANGUAGES = [
    {"code": "fr", "name": "Français"},
    {"code": "en", "name": "English"},
    {"code": "mg", "name": "Malagasy"}
]

# ----- UTILITAIRES -----
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]
        if not token:
            return jsonify({"error": "Token manquant"}), 401
        try:
            data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            current_user = users_col.find_one({"username": data["username"]})
        except:
            return jsonify({"error": "Token invalide"}), 401
        return f(current_user, *args, **kwargs)
    return decorated

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
        "$or":[{"user1":user1,"user2":user2},{"user1":user2,"user2":user1}]
    })
    if relation:
        new_score = relation["score"] + points
        friendships_col.update_one(
            {"_id":relation["_id"]},
            {"$set":{"score":new_score,"planet":get_planet(new_score),"last_interaction":datetime.utcnow()}}
        )
    else:
        friendships_col.insert_one({
            "user1":user1,
            "user2":user2,
            "score":points,
            "planet":get_planet(points),
            "last_interaction":datetime.utcnow()
        })

# ----- ROUTES BASE -----
@app.route("/")
def home():
    return {"status":"Astra serveur actif"}

# ----- UTILISATEURS -----
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
    token = jwt.encode({"username":user["username"],"exp":datetime.utcnow()+timedelta(hours=24)}, app.config["SECRET_KEY"], algorithm="HS256")
    users_col.update_one({"_id":user["_id"]}, {"$set":{"online":True}})
    return jsonify({"message":"Connexion réussie","token":token})

@app.route("/logout", methods=["POST"])
@token_required
def logout(current_user):
    users_col.update_one({"_id":current_user["_id"]}, {"$set":{"online":False}})
    return jsonify({"message":"Déconnexion réussie"})

# ----- LANGUE -----
@app.route("/languages", methods=["GET"])
def get_languages():
    return jsonify(LANGUAGES)

@app.route("/choisir-langue", methods=["POST"])
@token_required
def choisir_langue(current_user):
    data = request.json
    code = data.get("code")
    if code not in [l["code"] for l in LANGUAGES]:
        return jsonify({"error":"Code langue invalide"}),400
    users_col.update_one({"_id":current_user["_id"]}, {"$set":{"langue":code}})
    return jsonify({"message":f"Langue réglée sur {code}"})

# ----- POSTS -----
@app.route("/post", methods=["POST"])
@token_required
@limiter.limit("10/minute")
def creer_post(current_user):
    data = request.json
    post = {"content":data["content"], "username":current_user["username"], "date":datetime.utcnow()}
    result = posts_col.insert_one(post)
    return jsonify({"message":"Post créé","post_id":str(result.inserted_id)})

@app.route("/posts")
def get_posts():
    posts = posts_col.find().sort("date",-1)
    output=[]
    for p in posts:
        likes = likes_col.count_documents({"post_id":str(p["_id"])})
        output.append({"id":str(p["_id"]),"content":p["content"],"author":p["username"],"likes":likes})
    return jsonify(output)

# ----- LIKE -----
@app.route("/like", methods=["POST"])
@token_required
@limiter.limit("20/minute")
def like(current_user):
    data = request.json
    if likes_col.find_one({"username":current_user["username"],"post_id":data["post_id"]}):
        return jsonify({"message":"Déjà liké"}),400
    likes_col.insert_one({"username":current_user["username"],"post_id":data["post_id"],"date":datetime.utcnow()})
    post = posts_col.find_one({"_id":data["post_id"]})
    if post:
        update_friendship(current_user["username"], post["username"], 1)
        notifications_col.insert_one({"type":"like","from":current_user["username"],"to":post["username"],"post_id":data["post_id"],"date":datetime.utcnow()})
    return jsonify({"message":"Like ajouté"})

# ----- COMMENTAIRES -----
@app.route("/comment", methods=["POST"])
@token_required
def comment(current_user):
    data = request.json
    comment = {"post_id":data["post_id"],"username":current_user["username"],"content":data["content"],"date":datetime.utcnow()}
    comments_col.insert_one(comment)
    post = posts_col.find_one({"_id":data["post_id"]})
    if post:
        update_friendship(current_user["username"], post["username"], 1)
        notifications_col.insert_one({"type":"comment","from":current_user["username"],"to":post["username"],"post_id":data["post_id"],"date":datetime.utcnow()})
    return jsonify({"message":"Commentaire ajouté"})

@app.route("/comments/<post_id>")
def get_comments(post_id):
    comments = comments_col.find({"post_id":post_id})
    output=[{"user":c["username"],"content":c["content"]} for c in comments]
    return jsonify(output)

# ----- FOLLOW -----
@app.route("/follow", methods=["POST"])
@token_required
def follow(current_user):
    data = request.json
    if follows_col.find_one({"follower":current_user["username"],"followed":data["followed"]}):
        return jsonify({"message":"Déjà suivi"}),400
    follows_col.insert_one({"follower":current_user["username"],"followed":data["followed"],"date":datetime.utcnow()})
    update_friendship(current_user["username"], data["followed"], 5)
    notifications_col.insert_one({"type":"follow","from":current_user["username"],"to":data["followed"],"date":datetime.utcnow()})
    return jsonify({"message":"Utilisateur suivi"})

# ----- MESSAGE -----
@app.route("/message", methods=["POST"])
@token_required
def message(current_user):
    data = request.json
    msg={"sender":current_user["username"],"receiver":data["receiver"],"content":data["content"],"date":datetime.utcnow()}
    messages_col.insert_one(msg)
    update_friendship(current_user["username"], data["receiver"], 3)
    notifications_col.insert_one({"type":"message","from":current_user["username"],"to":data["receiver"],"date":datetime.utcnow()})
    return jsonify({"message":"Message envoyé"})

@app.route("/messages/<username>")
@token_required
def get_messages(current_user, username):
    user_id = username
    query={"$or":[{"sender":user_id},{"receiver":user_id}]}
    messages=messages_col.find(query).sort("date",-1)
    output=[{"id":str(m["_id"]),"content":m["content"],"sender":m["sender"],"receiver":m["receiver"]} for m in messages]
    return jsonify(output)

# ----- PLANETES AMIS -----
@app.route("/planetes/<username>")
@token_required
def planetes(current_user, username):
    relations=friendships_col.find({"$or":[{"user1":username},{"user2":username}]})
    output=[{"friend":r["user2"] if r["user1"]==username else r["user1"],"planet":r["planet"],"score":r["score"]} for r in relations]
    return jsonify(output)

# ----- NOTIFICATIONS -----
@app.route("/notifications/<username>")
@token_required
def notifications(current_user, username):
    notif=notifications_col.find({"to":username}).sort("date",-1)
    output=[{"type":n["type"],"from":n["from"],"date":n["date"]} for n in notif]
    return jsonify(output)

# ----- RECHERCHE -----
@app.route("/search")
@token_required
def search(current_user):
    username=request.args.get("username","")
    users=users_col.find({"username":{"$regex":username,"$options":"i"}})
    output=[{"username":u["username"]} for u in users]
    return jsonify(output)

# ----- PROFIL -----
@app.route("/profil/<username>")
@token_required
def profil(current_user, username):
    user=users_col.find_one({"username":username})
    if not user:
        return jsonify({"error":"Utilisateur introuvable"}),404
    followers=follows_col.count_documents({"followed":username})
    following=follows_col.count_documents({"follower":username})
    posts=posts_col.count_documents({"username":username})
    return jsonify({"username":username,"bio":user.get("bio",""),"followers":followers,"following":following,"posts":posts,"langue":user.get("langue","fr")})

# ----- RUN SERVER -----
if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000,debug=True)
