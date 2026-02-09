# Инструкции Dockerfile: Практические Сценарии

## Практические сценарии

### Переопределение `ENTRYPOINT` и `CMD`

**Золотое правило:** `docker-compose.yml` (или `docker run`) всегда имеет приоритет над `Dockerfile`.

1. `command:` в `compose.yml` (или аргументы в `docker run`) **заменяет** `CMD` из `Dockerfile`.
2. `entrypoint:` в `compose.yml` (или `--entrypoint` в `docker run`) **заменяет** `ENTRYPOINT` из `Dockerfile`.

| В `Dockerfile` | В `docker-compose.yml` / `docker run` | Что в итоге запустится |
| :--- | :--- | :--- |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | (ничего не указано) | `/app/run --default`<br>*(Используются оба значения из Dockerfile)* |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `command: --prod` | `/app/run --prod`<br>*(**`command` заменил `CMD`**. ENTRYPOINT остался)* |
| `ENTRYPOINT ["/app/run"]` | `entrypoint: /app/debug` | `/app/debug`<br>*(entrypoint заменил ENTRYPOINT. CMD исчез)* |
| `ENTRYPOINT ["/app/run"]`<br>`CMD ["--default"]` | `entrypoint: /app/debug`<br>`command: --verbose` | `/app/g/debug --verbose`<br>*(Заменились и ENTRYPOINT, и CMD)* |

**Практический пример**

Допустим, у вас есть `Dockerfile`:

```dockerfile
FROM alpine:3.20.0
ENTRYPOINT ["ping", "-c", "3"]
CMD ["localhost"]
```

По умолчанию этот контейнер будет пинговать `localhost`.

Теперь в `docker-compose.yml` вы хотите пинговать другой хост:

```yaml
services:
  pinger:
    build: .
    command: google.com
```

Когда вы запустите `docker compose up`, выполнится команда `ping -c 3 google.com`, потому что `command: google.com` из `compose.yml` заменил `CMD ["localhost"]` из `Dockerfile`.
