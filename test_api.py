import requests

response = requests.post(
    "http://localhost:8000/chat",
    json={
        "message": "",
        "conversation_history": [],
        "job_role": "Software Engineer"
    }
)
print(response.status_code)
print(response.json())
