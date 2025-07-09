# **Запуск и создание**

---

### **Управление контекстом Docker**

- **Создать новый контекст**
```sh
docker context create <имя_контекста> --docker "host=ssh://<user>@<ip_address>:<port>"
```

- **Переключиться на другой контекст**
```sh
docker context use <имя_контекста>
```

---

### **Запуск с помощью Docker Compose**

- **Собрать и запустить контейнеры в фоновом режиме**
```sh
docker compose up -d --build
```