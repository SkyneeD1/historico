# Imagem base com Python
FROM python:3.10

# Atualiza o sistema e instala dependências do camelot
RUN apt-get update && \
    apt-get install -y ghostscript python3-tk tesseract-ocr libglib2.0-0 libsm6 libxext6 libxrender-dev && \
    apt-get clean

# Cria o diretório da aplicação
WORKDIR /app

# Copia os arquivos para dentro do container
COPY . /app

# Instala as dependências
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Expõe a porta do Streamlit
EXPOSE 8501

# Comando para rodar o app
CMD ["streamlit", "run", "app2.py", "--server.port=8501", "--server.enableCORS=false"]
