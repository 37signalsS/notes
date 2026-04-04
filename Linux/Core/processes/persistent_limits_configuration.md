# Persistent Limits Configuration

## Определения

**Persistent Limits (постоянные лимиты)** — настройки ресурсных ограничений, сохраняемые между перезагрузками системы. Применяются через конфигурационные файлы systemd или PAM, в отличие от временных лимитов `ulimit`.

## Основные концепции

Постоянные лимиты настраиваются двумя основными способами:

1. **systemd юнит-файлы** — предпочтительный метод для сервисов/демонов
2. **`/etc/security/limits.conf`** — классический метод для пользовательских сессий (через PAM)

Подробное описание механизмов, иерархии применения и всех доступных директив см. в [**Resource Limits Concepts**](./resource_limits_concepts.md).

## Практические сценарии

### Настройка лимитов для systemd-сервиса

```ini
# /etc/systemd/system/my-app.service
[Service]
LimitNOFILE=65536      # Лимит на количество открытых файлов
LimitNPROC=2048        # Лимит на количество процессов
LimitCORE=infinity     # Лимит на размер core-файла
LimitAS=8G             # Лимит на адресное пространство
OOMScoreAdjust=-1000   # Защита от OOM Killer
```

Применение изменений:

```bash
sudo systemctl daemon-reload
sudo systemctl restart my-app
```

> **Примечание:** Для override-файлов используйте `sudo systemctl edit my-app.service` — systemd создаст `/etc/systemd/system/my-app.service.d/override.conf` автоматически.

### Настройка лимитов для пользовательских сессий

```bash
# /etc/security/limits.conf
# <domain>  <type>  <item>    <value>
# ------------------------------------
*           soft    nofile    65536
*           hard    nofile    131072
student     hard    nproc     1024
@usergroup  hard    as        2048000  # Лимит адресного пространства (KB)
```

> **Важно:** Для применения изменений пользователь должен перезайти в систему (logout/login). Файл обрабатывается модулем `pam_limits.so`.

### Глобальные настройки для всех сервисов

```bash
# /etc/systemd/system.conf
DefaultLimitNOFILE=65536
DefaultLimitNPROC=4096
DefaultLimitCORE=0
```

Применение:

```bash
sudo systemctl daemon-reload
```

> **Примечание:** `DefaultLimit*` в `system.conf` применяются ко всем сервисам, не имеющим явных настроек лимитов. Индивидуальные настройки юнита имеют приоритет.

## Дополнительная информация

### Выбор механизма

| Сценарий | Механизм | Файл |
| :--- | :--- | :--- |
| Системный сервис/демон | systemd | `/etc/systemd/system/<service>.service` |
| Пользовательская сессия (SSH, GUI) | PAM/limits.conf | `/etc/security/limits.conf` |
| Все сервисы (глобально) | systemd system.conf | `/etc/systemd/system.conf` |
| Контейнеры | cgroups v2 | `/sys/fs/cgroup/...` |

### Важные замечания

- **systemd не использует PAM** — настройки `limits.conf` не влияют на сервисы, управляемые `systemd`
- **cgroups v2 имеют приоритет** — если контейнер ограничен через cgroups, настройки systemd/limits.conf не помогут превысить этот лимит
- **Перезапуск обязателен** — изменения вступают в силу только после `daemon-reload` + `restart`

---

Временная настройка лимитов описана в [**Ulimit Usage**](./ulimit_usage.md). Иерархия применения — в [**Limits Hierarchy**](./limits_hierarchy.md).
