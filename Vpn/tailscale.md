### Регистрация нового устройства

*   **Linux:**
    Выполните в терминале команду, указав адрес вашего сервера Headscale.
    ```bash
    # Замените https://headscale.example.com на адрес вашего сервера(https://headscale.magicfun.nnstd.dev)
    sudo tailscale up --login-server https://headscale.example.com
    ```
    Скопируйте ключ (`mkey...`), который появится в выводе.

*   **Windows / macOS / Android:**
    1.  В настройках приложения найдите опцию для использования альтернативного сервера (`Use alternative coordination server`).
    2.  Введите адрес вашего сервера Headscale: `https://headscale.example.com`.
    3.  Нажмите `Log in` или `Подключиться`. В браузере откроется страница с ключом аутентификации.
    4.  Скопируйте этот ключ (`mkey...`).

**Регистрация ключа на сервере**

Подключитесь к вашему серверу Headscale (например, по SSH) и выполните команду:

```bash
headscale nodes register --user <user> --key <key>
```

### Настройка Exit Node

Чтобы маршрутизировать весь трафик устройства через другой узел в вашей сети (exit node):

    ```bash
    sudo tailscale set --exit-node-allow-lan-access=true --exit-node=<exit-node-name>
    ```
---

## Управление сервером Headscale

*   **Создание нового пользователя:**
    ```bash
    headscale users create <username>
    ```

*   **Просмотр списка всех узлов:**
    ```bash
    headscale nodes list
    ```

*   **Удаление неактивного узла:**
    ```bash
    headscale nodes delete --identifier <ID>
    ```

### Управление доступом (ACL)

Правила доступа между устройствами настраиваются в файле `acl.hujson` (или `acl.json`) на сервере.

```hujson
{
  // Группы пользователей для удобного управления доступом.
  "groups": {
    "group:admins": ["user1@example.com", "misha"],
    "group:services": ["autogroup:self"],
  },

  // Определения хостов для статических IP или псевдонимов.
  "hosts": {
    "monitoring": "100.64.0.1",
    "kaguya-exit-node": "100.64.0.2",
  },

  // Основной раздел с правилами доступа.
  "acls": [
    // Администраторы имеют доступ ко всем устройствам.
    {
      "action": "accept",
      "src": ["group:admins"],
      "dst": ["*:*"],
    },
    // Разрешить всем в сети использовать exit-node.
    {
      "action": "accept",
      "src": ["autogroup:members"],
      "dst": ["kaguya-exit-node:*"],
    },
  ],

  // Тесты для проверки правил ACL (опционально).
  "tests": [
    {
      "src": "misha",
      "accept": ["monitoring:80"],
      "deny": ["100.64.0.3:22"],
    },
  ],
}
```

**Важно:** После внесения изменений в файл ACL перезапустите Headscale для их применения.

```bash
# Пример для Docker Compose
docker compose restart headscale

# Пример для systemd
sudo systemctl restart headscale
```
