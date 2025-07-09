# Установка и настройка Ollama и Open WebUI

Это руководство поможет вам установить Ollama и настроить Open WebUI для взаимодействия с моделями.

## 1. Установка Ollama

Выполните следующую команду, чтобы скачать и запустить официальный скрипт установки Ollama:

```sh
curl -fsSL https://ollama.com/install.sh | sh
```

После установки вы можете запустить модель, например, `llama3.1`:

```sh
ollama run llama3.1
```

## 2. Настройка и запуск Open WebUI

Open WebUI — это удобный веб-интерфейс для работы с Ollama.

### Конфигурация Ollama для сетевого доступа

Чтобы Open WebUI мог подключиться к Ollama, необходимо разрешить Ollama принимать запросы со всех сетевых интерфейсов.

1.  Откройте файл службы `ollama.service` для редактирования:

    ```sh
    sudo nano /etc/systemd/system/ollama.service
    ```

2.  В секции `[Service]` добавьте следующую строку:

    ```
    Environment="OLLAMA_HOST=0.0.0.0"
    ```

3.  Перезагрузите конфигурацию `systemd` и перезапустите сервис Ollama:
    ```sh
    sudo systemctl daemon-reload
    sudo systemctl restart ollama
    ```
### Запуск Open WebUI с помощью Docker

1.  Убедитесь, что Docker запущен и включен:

    ```sh
    sudo systemctl enable --now docker
    ```

2.  Запустите контейнер Open WebUI:

    ```sh
    docker run -d --network=host -v open-webui:/app/backend/data -e OLLAMA_BASE_URL=http://127.0.0.1:11434 --name open-webui --restart always ghcr.io/open-webui/open-webui:main
    ```

    > **Примечание:** Мы используем `--network=host`, чтобы контейнер имел доступ к сервису Ollama, работающему на `localhost`.

### Доступ и устранение неполадок

После успешного запуска вы можете открыть Open WebUI в браузере по адресу: [http://localhost:8080](http://localhost:8080)

**Если возникли проблемы с контейнером `open-webui`**, вы можете остановить и удалить его, чтобы затем запустить заново:

```sh
docker stop open-webui
docker rm open-webui
```