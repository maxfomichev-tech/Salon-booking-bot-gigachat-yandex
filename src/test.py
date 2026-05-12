import requests
requests.packages.urllib3.disable_warnings()

token = "ВАШ_ТОКЕН"
headers = {"Authorization": f"OAuth {token}"}

# Тест 1: Информация о диске
r = requests.get("https://cloud-api.yandex.net/v1/disk/", headers=headers, verify=False)
print("Status:", r.status_code)
print("Body:", r.text[:200])

# Тест 2: Проверка файла
r = requests.get("https://cloud-api.yandex.net/v1/disk/resources", 
                 headers=headers, 
                 params={"path": "/salon-bot/clients.xlsx"},
                 verify=False)
print("File check:", r.status_code)