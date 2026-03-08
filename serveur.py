from flask import Flask, jsonify, request
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId

# ----- INITIALISATION -----
app = Flask(__name__) 

@app.route('/')
def home():
    return {
        "statut": "en ligne",
        "message": "Bienvenue sur l'API Astra-serveur2",
        "auteur": "Alan Mitha",
        "version": "1.0"
    }
# Ton lien MongoDB modifié depuis ton bloc-notes
MONGO_URI = "mongodb+srv://AlanMitha:252627shamilmitha02@cluster0.epdfpxp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(MONGO_URI)
db = client['AstraDB'] # Nom de ta base de données

# Collections (équivalent des tables)
users_col = db['users']
posts_col = db['posts']
likes_col = db['likes']
follows_col = db['follows']
messages_col = db['messages']

# ----- LANGUES -----
LANGUAGES = [
    {"code": "fr", "name": "Français"},
    {"code": "en", "name": "English"},
    {"code": "mg", "name": "Malagasy"}
]

# ----- UTILITAIRES -----
def get_user_by_username(username):
    user = users_col.find_one({"username": username})
    if not user:
        return None, jsonify({"error": f"Utilisateur '{username}' non trouvé"}), 404
    return user, None, None

# ----- ROUTES LANGUES -----
@app.route("/languages", methods=["GET"])
def get_languages():
    return jsonify(LANGUAGES)

@app.route("/choisir-langue", methods=["POST"])
def choisir_langue():
    data = request.json
    username = data.get("username")
    code = data.get("code")
    user, error, status = get_user_by_username(username)
    if error: return error, status
    
    if code not in [l['code'] for l in LANGUAGES]:
        return jsonify({"error": "Code langue invalide"}), 400
    
    users_col.update_one({"username": username}, {"$set": {"langue": code}})
    return jsonify({"message": f"Langue de {username} réglée sur : {code}"})

# ----- ROUTES UTILISATEUR -----
@app.route("/utilisateurs", methods=["POST"])
def creer_utilisateur():
    data = request.json
    if users_col.find_one({"username": data['username']}):
        return jsonify({"error": "Nom d'utilisateur déjà utilisé"}), 400
    if users_col.find_one({"email": data['email']}):
        return jsonify({"error": "Email déjà utilisé"}), 400

    hashed_password = generate_password_hash(data['password'])
    new_user = {
        "username": data['username'],
        "email": data['email'],
        "password": hashed_password,
        "langue": "fr"
    }
    users_col.insert_one(new_user)
    return jsonify({"message": f"Utilisateur {data['username']} créé avec succès"})

@app.route("/utilisateurs", methods=["GET"])
def get_users():
    users = users_col.find()
    return jsonify([{"username": u['username'], "email": u['email'], "langue": u.get('langue', 'fr')} for u in users])

# ----- ROUTES PUBLICATION -----
@app.route("/post", methods=["POST"])
def creer_post():
    data = request.json
    user, error, status = get_user_by_username(data['username'])
    if error: return error, status
    
    post = {
        "content": data['content'],
        "user_id": str(user['_id']),
        "author_name": user['username']
    }
    result = posts_col.insert_one(post)
    return jsonify({"message": "Publication ajoutée", "id_post": str(result.inserted_id)})

@app.route("/posts", methods=["GET"])
def get_posts():
    posts = posts_col.find()
    output = []
    for p in posts:
        likes_count = likes_col.count_documents({"post_id": str(p['_id'])})
        output.append({
            "id": str(p['_id']),
            "content": p['content'],
            "author": p.get('author_name', 'Unknown'),
            "likes": likes_count
        })
    return jsonify(output)

# ----- LIKE -----
@app.route("/like", methods=["POST"])
def like_post():
    data = request.json
    user, error, status = get_user_by_username(data['username'])
    if error: return error, status
    
    if likes_col.find_one({"user_id": str(user['_id']), "post_id": data['post_id']}):
        return jsonify({"message": "Déjà liké"}), 400
    
    likes_col.insert_one({"user_id": str(user['_id']), "post_id": data['post_id']})
    return jsonify({"message": f"{user['username']} a liké le post {data['post_id']}"})

# ----- FOLLOW -----
@app.route("/follow", methods=["POST"])
def follow_user():
    data = request.json
    follower, error, status = get_user_by_username(data['follower'])
    if error: return error, status
    followed, error, status = get_user_by_username(data['followed'])
    if error: return error, status
    
    if follows_col.find_one({"follower_id": str(follower['_id']), "followed_id": str(followed['_id'])}):
        return jsonify({"message": "Déjà suivi"}), 400
        
    follows_col.insert_one({"follower_id": str(follower['_id']), "followed_id": str(followed['_id'])})
    return jsonify({"message": f"{follower['username']} suit {followed['username']}"})

# ----- MESSAGE -----
@app.route("/message", methods=["POST"])
def envoyer_message():
    data = request.json
    sender, error, status = get_user_by_username(data['sender'])
    if error: return error, status
    receiver, error, status = get_user_by_username(data['receiver'])
    if error: return error, status
    
    message = {
        "content": data['content'],
        "sender_id": str(sender['_id']),
        "receiver_id": str(receiver['_id']),
        "sender_name": sender['username'],
        "receiver_name": receiver['username']
    }
    messages_col.insert_one(message)
    return jsonify({"message": f"Message envoyé de {sender['username']} à {receiver['username']}"})

@app.route("/messages/<username>", methods=["GET"])
def get_messages(username):
    user, error, status = get_user_by_username(username)
    if error: return error, status
    
    user_id = str(user['_id'])
    query = {"$or": [{"sender_id": user_id}, {"receiver_id": user_id}]}
    messages = messages_col.find(query)
    
    output = []
    for m in messages:
        output.append({
            "id": str(m['_id']),
            "content": m['content'],
            "sender": m.get('sender_name', 'Unknown'),
            "receiver": m.get('receiver_name', 'Unknown')
        })
    return jsonify(output)

# ----- MAIN -----
if __name__ == "__main__":

    app.run(host='0.0.0.0', port=5000, debug=True)
