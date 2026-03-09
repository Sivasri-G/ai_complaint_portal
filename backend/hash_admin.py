from flask_bcrypt import Bcrypt
from flask import Flask

app = Flask(__name__)
bcrypt = Bcrypt(app)

password = "Admin@123"
hashed = bcrypt.generate_password_hash(password).decode("utf-8")

print(hashed)
