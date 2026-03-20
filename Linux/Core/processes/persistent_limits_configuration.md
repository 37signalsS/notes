# Persistent Limits Configuration

## Постоянная настройка лимитов

#### 1. Для сервисов `systemd` (предпочтительный способ)

Лимиты устанавливаются прямо в юнит-файле сервиса.

```ini
# /etc/systemd/system/my-app.service
[Service]
LimitNOFILE=65536      # Лимит на количество открытых файлов
LimitNPROC=2048        # Лимит на количество процессов
LimitCORE=infinity     # Лимит на размер core-файла
LimitAS=8G             # Лимит на адресное пространство
OOMScoreAdjust=-1000   # Защита от OOM Killer
```

После изменения файла:

```bash
sudo systemctl daemon-reload
sudo systemctl restart my-app
```

#### 2. Для пользовательских сессий (классический способ)

Используется файл `/etc/security/limits.conf`.

```bash
# /etc/security/limits.conf
# <domain>  <type>  <item>    <value>
# ------------------------------------
*           soft    nofile    65536
*           hard    nofile    131072
student     hard    nproc     1024
@usergroup  hard    as        2048000  # Лимит адресного пространства (virtual memory) в КБ
```

> **Важно:** Для применения изменений пользователь должен перезайти в систему (logout/login).

---

**См. также:**

* [Использование ulimit](./ulimit_usage.md)
* [Иерархия применения лимитов](./limits_hierarchy.md)
