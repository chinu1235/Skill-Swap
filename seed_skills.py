
from pymongo import MongoClient
from dotenv import dotenv_values

config = dotenv_values("backend/.env")

uri = config.get("MONGODB_URI") or config.get("MONGO_URI")
db_name = (
    config.get("MONGODB_DB_NAME")
    or config.get("MONGO_DB_NAME")
    or "skillswap_db"
)

if not uri:
    raise ValueError("MongoDB URI not found in backend/.env")

client = MongoClient(uri, serverSelectionTimeoutMS=5000)
client.admin.command("ping")

db = client[db_name]

skills = [
    ("Web Development", "Technology"),
    ("Python", "Programming"),
    ("App Development", "Technology"),
    ("UI/UX Design", "Design"),
    ("Graphic Design", "Design"),
    ("Video Editing", "Media"),
    ("Data Analytics", "Data"),
    ("Digital Marketing", "Marketing"),
]

for name, category in skills:
    db.skills.update_one(
        {"skill_name": name},
        {
            "$setOnInsert": {
                "skill_name": name,
                "category": category,
            }
        },
        upsert=True,
    )

print("Total skills:", db.skills.count_documents({}))
client.close()
