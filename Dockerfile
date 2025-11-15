# Utiliser une image de base fournie par NVIDIA avec CUDA et Python
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Définir des variables d'environnement pour éviter les questions interactives
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Ajouter le PPA deadsnakes pour Python 3.12
RUN apt-get update && apt-get install -y software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip git \
    && rm -rf /var/lib/apt/lists/*

# Définir python3.12 comme le python par défaut
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances et les installer
COPY requirements.txt .
# Mettre à jour pip avant d'installer les paquets
RUN pip install --no-cache-dir --upgrade pip
# Installer tensorflow[and-cuda] pour la prise en charge du GPU
RUN pip install --no-cache-dir -r requirements.txt tensorflow[and-cuda]

# Copier le reste du code de l'application
COPY . .

# Exposer le port pour l'API de contrôle (si nécessaire)
EXPOSE 8008

# La commande par défaut (sera surchargée par docker-compose pour chaque service)
CMD ["python", "main_acquirer.py"]