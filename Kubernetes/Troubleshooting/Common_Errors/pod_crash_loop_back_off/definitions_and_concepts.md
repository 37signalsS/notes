# Pod в состоянии `CrashLoopBackOff`: Определения и концепции

## Определения

**`CrashLoopBackOff`** — статус пода, означающий, что контейнер запускается, но немедленно завершается с ошибкой. `kubelet` пытается перезапустить контейнер, но сбой повторяется циклически с нарастающей задержкой между попытками (exponential backoff).

**Backoff задержки:** 10s → 20s → 40s → 80s → 160s → 300s (максимум)

## Основные концепции

### Механизм перезапуска

```
Контейнер запускается
    ↓
Приложение падает (Exit Code ≠ 0)
    ↓
kubelet ждет (exponential backoff)
    ↓
Попытка перезапуска
    ↓
Цикл повторяется → CrashLoopBackOff
```

### Коды выхода (Exit Codes)

| Код | Значение | Вероятная причина |
|-----|----------|-------------------|
| **0** | Успех | Нормальное завершение (не для долгоживущих процессов) |
| **1** | Общая ошибка | Ошибка приложения, конфигурации |
| **126** | Command not executable | Проблема с правами на файл |
| **127** | Command not found | Неверный путь к команде |
| **137** | OOMKilled (128+9) | Превышен лимит памяти |
| **143** | SIGTERM (128+15) | Graceful shutdown |
| **1** - **255** | Различные ошибки | См. документацию приложения |

> **См. также:** [`docker_exit_codes.md`](../../../Docker/Docker_troubleshooting/docker_exit_codes.md)

### Причины CrashLoopBackOff по категориям

| Категория | Примеры | % случаев |
|-----------|---------|-----------|
| **Приложение** | Неперехваченное исключение, баг кода | ~35% |
| **Конфигурация** | Отсутствует ConfigMap/Secret, неверные env vars | ~30% |
| **Зависимости** | Недоступна БД, кэш, внешний сервис | ~20% |
| **Ресурсы** | OOMKilled, нехватка CPU | ~10% |
| **Probes** | Неудачная livenessProbe | ~5% |

### Связанные концепты

- Общие инструменты диагностики: [`troubleshooting_overview.md`](../troubleshooting_overview.md)
- OOMKilled: [`oomkilled_pods.md`](./oomkilled_pods.md)
- QoS и ресурсы: [`qos_limit_and_requests.md`](../../Scheduling/qos_limit_and_requests.md)
- RBAC: [`rbac_overview.md`](../../Security/rbac/rbac_overview.md)
- ConfigMap/Secret: [`pod_volumes.md`](../../Base/Pod/pod_volumes.md)

---

## Ссылки

- [Практические сценарии](./practical_scenarios.md) — диагностика и решения
- [Дополнительная информация](./advanced_topics.md) — автоматизация, best practices
