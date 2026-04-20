# GEO Artemis

<img width="1913" height="905" alt="image" src="https://github.com/user-attachments/assets/9a523384-ca06-4784-92fe-70a35a500d0f" />




## The Propesd System
The proposed system is an AI-powered global hazard monitoring and analysis platform designed to transform fragmented disaster data into structured, actionable intelligence. It integrates real-time satellite feeds, historical datasets, and external APIs to continuously track natural hazard events such as wildfires, typhoons, volcanic activity, and iceberg movements. Unlike traditional systems that rely on delayed reporting, this platform emphasizes near real-time data ingestion and processing. By capturing key spatiotemporal attributes—including latitude, longitude, time, and event intensity—the system builds a unified data pipeline that serves as the foundation for advanced geospatial analytics. This allows stakeholders to observe global hazard activity as it unfolds, enabling faster awareness and more informed decision-making.

At the core of the system lies an unsupervised machine learning approach using DBSCAN (Density-Based Spatial Clustering of Applications with Noise). This algorithm plays a critical role in identifying meaningful patterns within large volumes of geospatial data without requiring predefined labels. DBSCAN groups events based on spatial proximity and density, effectively discovering natural hazard regions while filtering out noise or isolated incidents. As a result, the system can differentiate between structured hazards, such as typhoons that follow predictable paths, and more chaotic phenomena like wildfires that exhibit scattered patterns. This clustering mechanism enables the automatic detection of emerging hazard zones and provides a dynamic understanding of how events are distributed geographically over time.

Beyond clustering, the platform incorporates a robust risk assessment framework that evaluates the severity and evolution of hazard regions. Each identified cluster is analyzed using multiple dimensions, including event frequency, average intensity, duration of activity, and temporal growth trends. A base risk score is computed by combining the number of events with their average intensity, reflecting both occurrence and severity. This score is further enhanced through a time-aware component that considers recent activity compared to historical patterns, producing a time-adjusted risk score. Regions experiencing rapid increases in activity are therefore prioritized as high-risk zones. This approach allows the system to move beyond static analysis and instead highlight areas where hazards are intensifying, offering early indicators of potential escalation.

To ensure usability and practical impact, the system presents its insights through an interactive and visually rich interface. A 3D globe provides a global, real-time view of hazard events, while a complementary 2D dashboard offers detailed cluster visualizations, analytical charts, and risk-based mappings. Users can explore hazard distributions, compare event types, and identify high-risk regions with clarity. Additionally, integrated news and video feeds provide contextual information, bridging the gap between raw data and real-world developments. Together, these components create a comprehensive decision-support system that enhances situational awareness and supports proactive disaster management. While current capabilities focus on detection, clustering, and risk estimation, the platform establishes a strong foundation for future extensions into predictive modeling and advanced forecasting.


## RUN COMMAND IN TERMINAL

```
uvicorn Main.run:app --reload

