# Установка и настройка Ollama и Open WebUI

Выполните следующую команду, чтобы скачать и запустить официальный скрипт установки Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

После установки вы можете запустить модель, например, `llama3.1`:

```bash
ollama run llama3.1
```

## Конфигурация Ollama для сетевого доступа

Чтобы Open WebUI мог подключиться к Ollama, необходимо разрешить Ollama принимать запросы со всех сетевых интерфейсов.

1. Откройте файл службы `ollama.service` для редактирования:

    ```bash
    sudo systemctl edit ollama.service
    ```

2. В открывшемся редакторе добавьте следующие строки:

    ```ini
    [Service]
    Environment="OLLAMA_HOST=0.0.0.0"
    ```

3. Перезагрузите конфигурацию `systemd` и перезапустите сервис Ollama:

    ```bash
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    ```

### Запуск Open WebUI с помощью Docker

1. Убедитесь, что Docker запущен и включен:

    ```bash
    sudo systemctl enable --now docker
    ```

2. Запустите контейнер Open WebUI:

    ```bash
    docker run -d \
      --network=host \
      -v open-webui:/app/backend/data \
      -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
      --name open-webui \
      --restart always \
      ghcr.io/open-webui/open-webui:v0.6.32
    ```

    **Объяснение флагов `docker run`:**
    - `-d`: Запуск контейнера в фоновом режиме.
    - `--network=host`: Использование сетевого стека хоста, что позволяет контейнеру легко подключаться к сервисам, работающим на `localhost`.
    - `-v open-webui:/app/backend/data`: Создание и использование Docker-вольюма `open-webui` для сохранения данных Open WebUI.
    - `-e OLLAMA_BASE_URL=http://127.0.0.1:11434`: Установка переменной окружения, указывающей на адрес API Ollama.
    - `--name open-webui`: Присвоение имени контейнеру для удобства управления.
    - `--restart always`: Автоматический перезапуск контейнера при сбоях или после перезагрузки системы.
    - `ghcr.io/open-webui/open-webui:v0.6.32`: Образ контейнера Open WebUI.

### Доступ и устранение неполадок

После успешного запуска вы можете открыть Open WebUI в браузере по адресу: [http://localhost:8080](http://localhost:8080)

**Если возникли проблемы с контейнером `open-webui`**, вы можете остановить и удалить его, чтобы затем запустить заново:

```bash
docker stop open-webui
docker rm open-webui
```

После этого повторите команду `docker run` из предыдущего шага.
