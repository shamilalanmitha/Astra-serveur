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

app = Flask(__name__)

# ----- CONFIG -----
SECRET_KEY = os.getenv("SECRET_KEY", "ChangeThisSecret")
MONGO_URI = os.getenv("MONGO_URI")

app.config["SECRET_KEY"] = SECRET_KEY

# ----- RATE LIMIT -----
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

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
    return {"status": "Astra serveur actif 🚀"}


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


# ----- SEARCH USER -----
@app.route("/search")
def search():

    username = request.args.get("username","")

    users = users_col.find({
        "username":{
            "$regex":username,
            "$options":"i"
        }
    })

    output = []

    for u in users:
        output.append({
            "username":u["username"]
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


# ----- RUN SERVER (RENDER) -----
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
