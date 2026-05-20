# GEO Artemis

<img width="1913" height="905" alt="image" src="https://github.com/user-attachments/assets/9a523384-ca06-4784-92fe-70a35a500d0f" />

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white) ![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=flat-square&logo=chainlink&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat-square&logo=fastapi&logoColor=white) ![LangGraph](https://img.shields.io/badge/LangGraph-000000?style=flat-square&logo=graph&logoColor=white) ![Three.js](https://img.shields.io/badge/Three.js-000000?style=flat-square&logo=three.dot-js&logoColor=white) ![Leaflet](https://img.shields.io/badge/Leaflet-199903?style=flat-square&logo=Leaflet&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white) ![Globe.gl](https://img.shields.io/badge/Globe.gl-black?style=flat-square&logo=world&logoColor=white) ![Gemini AI](https://img.shields.io/badge/Gemini%20AI-8E75B2?style=flat-square&logo=google-gemini&logoColor=white) ![Tavily](https://img.shields.io/badge/Tavily-blue?style=flat-square)

`[Python]` `[LangChain]` `[LangGraph]` `[FastAPI]` `[Three.js]` `[Leaflet]` `[Docker]` `[Globe.gl]` `[Gemini AI]` `[Tavily]` `[Scikit-Learn]` `[Pandas]`

The proposed system is an AI-powered platform that monitors and analyzes natural hazards across the world. Its goal is to turn scattered disaster data into clear and useful information that people can act on.

The system collects data from multiple sources in near real time. It uses satellite data and public APIs, including NASA’s EONET for tracking events like wildfires, storms, volcanoes, and icebergs, and USGS data for monitoring earthquakes. Unlike traditional systems that depend on delayed reports, this platform keeps the data up to date by continuously processing events as they happen. It captures important details such as location (latitude and longitude), time, and intensity of each event.

All this information is combined into a single data pipeline, which is then used for geospatial analysis. This helps users clearly see where and when hazards are happening around the world, making it easier to respond quickly and make better decisions.

At the core of the system is an unsupervised machine learning approach based on HDBSCAN, which is well-suited for geospatial data with varying densities. Unlike traditional methods, the system applies clustering separately for each event type, allowing it to adapt to different spatial patterns such as dense cyclone paths and scattered wildfire occurrences.


### More Info Read Documentation.md
## RUN COMMAND IN TERMINAL

```
uvicorn Main.run:app --reload
```
`It deployed in render so please wait 40 50 seconds it take to open`

``
## Render deploy command
```
uvicorn main.run:app --host 0.0.0.0 --port $PORT
pip install --upgrade pip && pip install -r requirements.txt

PYTHON_VESION=3.10.0
