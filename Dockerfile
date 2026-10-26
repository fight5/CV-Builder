FROM python:3.11-slim

# Install TeX Live for PDF compilation
# texlive-lang-french est INDISPENSABLE : les templates utilisent
# \usepackage[french]{babel} (CV FR + lettre). Sans ce paquet, la
# compilation echoue. texlive-latex-recommended fournit xcolor/microtype.
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-lang-french \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p outputs

EXPOSE 8501

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501"]
