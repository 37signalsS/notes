# **Docker Compose**

Docker Compose — это инструмент для определения и запуска многоконтейнерных Docker-приложений. Он использует YAML-файл для конфигурации сервисов, сетей и томов вашего приложения.

- **Горячая перезагрузка:** Изменения, сделанные в `volumes` на хосте, автоматически подтягиваются в контейнер без необходимости его перезапуска.
- **Версии:** Часто используется `version: '2'`, так как с переходом на 3-ю версию часть функционала была перенесена в Docker Swarm.

---

### **Пример файла `docker-compose.yml`**

```yaml
name: taxi

services:
  web:
    build: .
    image: taxi
    restart: always
    env_file:
      - .env.production
    ports:
      - "100.64.0.13:3845:3000"
    depends_on:
      database:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://127.0.0.1:3000/api/health || exit 1"]
      interval: 2s
      start_period: 30s

  database:
    image: paradedb/paradedb
    restart: always
    ports:
      - "100.64.0.13:3856:5432"
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: IiQx4oSSM6JrjZHLf3pXNgBw7KTIjzRg
      POSTGRES_DB: taxi
      PGDATA: /database
    user: "0:0"
    volumes:
      - /mnt/external1/taxi/database:/database
    healthcheck:
      test: ["CMD-SHELL", "sh -c 'pg_isready -U postgres -d taxi'"]
      interval: 10s
      timeout: 30s
      retries: 3
      start_period: 80s
```

---

### **Объяснение ключевых параметров**

- `ports`: Пробрасывает порты в формате `ХОСТ:КОНТЕЙНЕР`. В примере `100.64.0.13:3845:3000` порт `3845` на хосте сопоставляется с портом `3000` внутри контейнера.
- `volumes`: Монтирует локальную директорию (`/mnt/external1/taxi/database`) в контейнер (`/database`).
- `depends_on`: Определяет зависимость старта одного сервиса от другого.
- `user`: Запускает процесс внутри контейнера от имени указанного пользователя (в данном случае, `root`).

---

### **Политики перезапуска (`restart`)**

- `no`: (По умолчанию) Контейнер не будет перезапущен автоматически.
- `on-failure:5`: Контейнер будет перезапущен только в случае завершения с ошибкой (ненулевой код выхода). Можно указать максимальное количество попыток (например, 5).
- `always`: Контейнер будет перезапускаться всегда, независимо от причины остановки.
- `unless-stopped`: Контейнер будет перезапускаться, если он был остановлен не вручную (например, из-за сбоя или перезагрузки Docker-демона).

---

### **Проверка состояния (`healthcheck`)**

`healthcheck` позволяет Docker проверять, работает ли приложение внутри контейнера корректно.

```yaml
healthcheck:
  test: ["CMD-SHELL", "sh -c 'pg_isready -U postgres -d taxi'"]
  interval: 10s       # Проверять каждые 10 секунд
  timeout: 30s        # Считать проверку неудачной через 30 секунд
  retries: 3          # 3 попытки перед тем, как пометить контейнер как нездоровый
  start_period: 80s   # Не выполнять проверку первые 80 секунд после старта
```

---

### **Обновление сервисов (`deploy`)**

Эта опция позволяет настроить стратегию обновления сервисов, что особенно полезно в Docker Swarm, но некоторые параметры применимы и для Compose.

```yaml
deploy:
  update_config:
    parallelism: 1
    delay: 10s
    order: start-first # Сначала запустить новый контейнер, затем остановить старый
```

Эта конфигурация лучше всего работает в сочетании с опцией `replicas`, чтобы развернуть несколько экземпляров одного и того же контейнера и обеспечить высокую доступность.

---

### **Полезные команды**

- **Масштабирование сервиса:**
  ```sh
  docker compose up -d --scale <service-name>=<number-of-containers>
  ```

- **Выполнение одноразовой команды:**
  ```sh
  docker compose run <service-name> <command>
  ```