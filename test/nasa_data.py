



import requests

url = "https://eonet.gsfc.nasa.gov/api/v3/events"
response = requests.get(url)
data = response.json()



events = data["events"]



import pandas as pd

rows = []

for event in events:
    for g in event["geometry"]:
        rows.append({
            "event": event["title"],
            "date": g["date"],
            "magnitude": g.get("magnitudeValue"),
            "lat": g["coordinates"][1],
            "lon": g["coordinates"][0]
        })

df = pd.DataFrame(rows)
#save in a folder
df.to_csv("Nasa_Event_data.csv", index=False)
print(df.head(30))

