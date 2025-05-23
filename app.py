# flask-oidc-provider/app.py

from flask import Flask, redirect, request, render_template, session, jsonify
from auth.token import TokenService
from auth.pkce import verify_pkce
from auth.client_auth import authenticate_client
from models import clients, authorization_codes, tokens, users
from config import Config
import os, uuid

app = Flask(__name__)
app.config.from_object(Config)

@app.route("/")
def index():
    return "OIDC Provider is Running"

@app.route("/.well-known/jwks.json")
def jwks():
    return Config.load_jwks(), 200, {"Content-Type": "application/json"}

@app.route("/authorize", methods=["GET", "POST"])
def authorize():
    if request.method == "GET":
        session['client_id'] = request.args.get("client_id")
        session['redirect_uri'] = request.args.get("redirect_uri")
        session['state'] = request.args.get("state")
        session['scope'] = request.args.get("scope")
        session['code_challenge'] = request.args.get("code_challenge")
        session['code_challenge_method'] = request.args.get("code_challenge_method")
        return render_template("login.html")

    username = request.form.get("username")
    password = request.form.get("password")
    user = users.get(username)

    if not user or user['password'] != password:
        return "Unauthorized", 401

    session['user'] = username
    return render_template("consent.html", client_id=session['client_id'], scope=session['scope'])

@app.route("/consent", methods=["POST"])
def consent():
    if "user" not in session:
        return "Unauthorized", 401

    code = str(uuid.uuid4())
    authorization_codes[code] = {
        "client_id": session['client_id'],
        "user": session['user'],
        "code_challenge": session['code_challenge']
    }
    redirect_uri = f"{session['redirect_uri']}?code={code}&state={session['state']}"
    return redirect(redirect_uri)

@app.route("/token", methods=["POST"])
def token():
    client, error = authenticate_client()
    if error:
        return error

    code = request.form.get("code")
    client_id = request.form.get("client_id")
    code_verifier = request.form.get("code_verifier")

    record = authorization_codes.get(code)
    if not record or record["client_id"] != client_id:
        return jsonify({"error": "invalid_grant"}), 400

    if not verify_pkce(record['code_challenge'], code_verifier):
        return jsonify({"error": "invalid_request"}), 400

    user = users[record['user']]
    id_token = TokenService.generate_id_token(user["sub"], client_id)
    access_token = TokenService.generate_access_token(user["sub"], session.get("scope", ""))
    refresh_token = TokenService.generate_refresh_token(user["sub"])

    tokens[access_token] = {"user": user, "client_id": client_id}
    tokens[refresh_token] = {"user": user, "client_id": client_id}

    return jsonify({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": 3600
    })

@app.route("/token/refresh", methods=["POST"])
def refresh_token():
    client, error = authenticate_client()
    if error:
        return error

    refresh_token = request.form.get("refresh_token")
    try:
        decoded = TokenService.decode_token(refresh_token)
        if decoded.get("type") != "refresh":
            return jsonify({"error": "Invalid token type"}), 400
        new_access_token = TokenService.generate_access_token(decoded["sub"], decoded.get("scope", ""))
        return jsonify({"access_token": new_access_token, "token_type": "Bearer", "expires_in": 1800})
    except Exception as e:
        return jsonify({"error": str(e)}), 401

@app.route("/userinfo", methods=["GET"])
def userinfo():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return "Missing token", 401

    token_value = auth_header.replace("Bearer ", "")
    data = tokens.get(token_value)
    if not data:
        return "Invalid token", 401

    user = data["user"]
    return jsonify({
        "sub": user["sub"],
        "name": user["name"],
        "email": user["email"]
    })

if __name__ == '__main__':
    app.run(debug=True)
