import os, time, requests
from dotenv import load_dotenv
load_dotenv()

key = os.environ['OPENAI_ADMIN_KEY']
end = int(time.time())
start = end - 86400  # last 24 hours

r = requests.get(
    'https://api.openai.com/v1/organization/costs',
    params={'start_time': start, 'end_time': end, 'bucket_width': '1d'},
    headers={'Authorization': f'Bearer {key}'},
)
print(f'Status: {r.status_code}')
print(r.json())