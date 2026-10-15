# Yandex Serverless Containers: Деплой ревизий

## 1. Определения

**Serverless Container (Serverless-контейнер)** — управляемый сервис Yandex Cloud для запуска контейнерных приложений без управления инфраструктурой. Автоматически масштабируется от 0 до N экземпляров.

**Ревизия (Revision)** — неизменяемая версия контейнера с фиксированным образом, ресурсами и переменными окружения. Деплой создаёт новую ревизию, переключая трафик.

**Concurrency** — максимальное количество запросов на один экземпляр. Ограничивает параллелизм и помогает управлять нагрузкой.

---

## 2. Базовые концепции

### Архитектура

```
Container (логическая группа) → Revision (immutable spec) → Instances (auto-scaled)
                                    ↑
                               cr.yandex/<image>
```

- **Container** — логическая сущность (аналог сервиса в Kubernetes).
- **Revision** — фиксированная конфигурация (immutable). Деплой = создание новой ревизии.
- **Instances** — автоматически масштабируются: 0 при простое, до N при нагрузке.

### Параметры ресурсов

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--cores` | Количество CPU | 1 |
| `--memory` | ОЗУ | 512M |
| `--concurrency` | Max запросов на инстанс | 4 |
| `--service-account-id` | SA для доступа к ресурсам | `<sa_id>` |

---

## 3. Практические сценарии

### Создание и деплой контейнера

```bash
# Создать serverless-контейнер
yc serverless container create --name my-app

# Деплой новой ревизии из образа CR
yc serverless container revision deploy \
  --container-name my-app \
  --image cr.yandex/<registry_id>/my-app:1.2.3 \
  --cores 1 \
  --memory 512M \
  --service-account-id <sa_id> \
  --concurrency 4
# → трафик переключается на новую ревизию
```

### Управление ревизиями

```bash
# Список ревизий
yc serverless container revision list --container-name my-app

# Откат на предыдущую ревизию
yc serverless container revision list --container-name my-app \
  --format json | jq -r '.[1].id' | \
  xargs yc serverless container revision deploy --container-name my-app --revision-id

# Обновление переменных окружения
yc serverless container revision deploy \
  --container-name my-app \
  --image cr.yandex/<registry_id>/my-app:1.2.3 \
  --cores 1 \
  --memory 512M \
  --env ENV=prod,LOG_LEVEL=info
```

---

## 4. Дополнительная информация

- **Автоскейлинг:** экземпляры запускаются при первом запросе и масштабируются до `--concurrency` запросов на инстанс.
- **Минимальная задержка:** cold start ~1-2 секунды (V8 containerd).
- **Сравнение с Cloud Functions:** serverless-контейнеры позволяют использовать любой runtime и образ, а не только поддерживаемые языки функций.
