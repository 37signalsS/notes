# **Установка OLLMA** 

``` sh
curl -fsSL https://ollama.com/install.sh | sh
```

``` sh
ollama run llama3.1
```
# **Openwebui**

``` sh
nano /etc/systemd/system/ollama.service
```

Добавляем Environment="OLLAMA_HOST=0.0.0.0"

``` sh
sudo systemctl enable --now docker.socket
```

``` sh
sudo systemctl enable --now docker
```

``` sh
docker run -d --network=host -v open-webui:/app/backend/data -e OLLAMA_BASE_URL=http://127.0.0.1:11434 --name open-webui --restart always ghcr.io/open-webui/open-webui:mainr
```

Если есть проблемы - docker stop openweui и  docker rm openwebui

http://localhost:8080
