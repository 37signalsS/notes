# Диагностические однострочники kubectl (k8s-debug)

## Определения

**k8s-debug** — категория рецептов быстрой диагностики кластера: однострочники `kubectl`, которые за одну команду отвечают на конкретный вопрос («кто падает», «почему Pending», «где OOMKilled»). Это не отдельный инструмент — все команды выполняются через `kubectl` и стандартные утилиты (`jq`, `python3`, `awk`).

**jsonpath** — язык запросов `kubectl` (`-o jsonpath='...'`) для извлечения полей из объектов API без `jq`; `{range ...}{end}` — цикл по массиву.

## Основные концепции

Три приёма лежат в основе большинства рецептов:

- **`--sort-by=<jsonpath>`** — сортировка `kubectl get` по любому полю (например, числу рестартов, потреблению памяти).
- **`--field-selector`** — серверная фильтрация (по фазе, причине, объекту) — предпочтительнее `grep` по выводу.
- **`-o jsonpath` + `xargs`** — массовая операция по списку ресурсов и извлечение вложенных полей.

Глубокая методология (уровни диагностики, алгоритм поиска причины) — в **[Поиск и устранение неисправностей](./troubleshooting_overview.md)**; теория каждой ошибки — в файлах подкаталога **[Common_Errors](./Common_Errors/)**.

## Практические сценарии

### Ресурсы и метрики

```bash
# Топ подов по числу рестартов — быстрый поиск crash-loop во всём кластере
kubectl get po -A --sort-by='.status.containerStatuses[0].restartCount' | tail -20

# Поды, отсортированные по потреблению памяти (требует metrics-server)
kubectl top pods -A --sort-by=memory | head -20

# Сырая статистика kubelet по подам — в обход metrics-server (Summary API)
kubectl get --raw /api/v1/nodes/<node>/proxy/stats/summary | jq '.pods[] | {name:.podRef.name, mem:.memory.workingSetBytes}'
```

### Конфигурация: ConfigMap, Secret, requests/limits

```bash
# Содержимое ConfigMap (поле data)
kubectl get cm <name> -n <ns> -o jsonpath='{.data}'

# Декодирование всех полей Secret (корректно для multi-key секретов)
kubectl get secret <name> -n <ns> -o jsonpath='{.data}' | python3 -c "import sys,json,base64; [print(k,'=',base64.b64decode(v).decode()) for k,v in json.load(sys.stdin).items()]"

# requests и limits каждого контейнера пода
kubectl get pod <pod> -n <ns> -o jsonpath='{range .spec.containers[*]}{.name}{"\t"}{.resources}{"\n"}{end}'
```

> Для одиночного ключа проще: `kubectl get secret <name> -o jsonpath='{.data.<key>}' | base64 -d`. Декодировать целый JSON через `base64 -d` нельзя — на multi-key секретах команда завершится ошибкой.

### События

```bash
# Warning-события конкретного пода в хронологии (kubectl events, v1.29+)
kubectl events --for pod/<pod> -n <ns> --types=Warning

# Стриминг событий пода
kubectl get events -n <ns> --field-selector involvedObject.name=<pod> --watch

# Причина ImagePullBackOff: ошибки pull — неверный тег, imagePullSecret, rate limit
kubectl get events -n <ns> --field-selector reason=Failed -o wide | grep -i 'pull\|manifest\|unauthorized'

# Логи предыдущего экземпляра упавшего контейнера с метками времени
kubectl logs <pod> -n <ns> -c <container> --previous --timestamps --tail=200
```

### Планирование и ноды

```bash
# Причины FailedScheduling для всех Pending-подов (taints, ресурсы, affinity)
kubectl get po -A --field-selector=status.phase=Pending -o name | xargs -I{} kubectl describe {} -n <ns> | grep -A3 FailedScheduling

# Триада диагностики NotReady: Conditions узла + хвост журнала kubelet
kubectl describe node <node> | grep -A12 Conditions; ssh <node> 'journalctl -u kubelet -n 100 --no-pager'

# Статистика conntrack на узле (переполнение nf_conntrack молча теряет пакеты)
kubectl debug node/<node> -it --image=nicolaka/netshoot -- conntrack -S
```

### Сеть и DNS

```bash
# Резолв FQDN сервиса из временного пода — отделяет проблемы CoreDNS от DNS приложения
kubectl run dnstest --rm -it --image=nicolaka/netshoot --restart=Never -- dig +short <name>.<ns>.svc.cluster.local
```

### Аудит namespace

```bash
# Все ресурсы всех типов в namespace — инвентаризация перед миграцией/очисткой
kubectl api-resources --verbs=list --namespaced -o name | xargs -I{} kubectl get {} -n <ns> --ignore-not-found

# Любой ресурс в плоском виде через jsonpath: namespace, имя, фаза
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}\t{.metadata.name}\t{.status.phase}\n{end}'
```

### Поиск OOMKilled по кластеру

```bash
# Поды, у которых последний выход контейнера — OOMKilled
kubectl get po -A -o jsonpath='{range .items[*]}{.metadata.namespace}{" "}{.metadata.name}{" "}{.status.containerStatuses[*].lastState.terminated.reason}{"\n"}{end}' | grep OOMKilled
```

## Устранение неполадок

| Симптом | Однострочник | Глубокий разбор |
|:---|:---|:---|
| Crash-loop, кто рестартится | `--sort-by='.status.containerStatuses[0].restartCount'` | [CrashLoopBackOff](./Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md) |
| OOMKilled по кластеру | jsonpath + `grep OOMKilled` | [OOMKilled](./Common_Errors/oomkilled_pods.md) |
| Поды Pending | `FailedScheduling` через `xargs describe` | [Ошибки планирования](./Common_Errors/pod_pending/definitions_and_concepts.md) |
| ImagePullBackOff | `reason=Failed` + `grep pull` | [Ошибки образов](./Common_Errors/PodImagePullErrors/definitions.md) |
| Нода NotReady | Conditions + `journalctl -u kubelet` | [Недоступность узла](./Common_Errors/NodeUnavailability/definitions.md) |
| Теряются пакеты на узле | `conntrack -S` через debug-node | [conntrack при pull образов](./Common_Errors/PodImagePullErrors/network_issues.md) |
| DNS не резолвит | `dnstest` + `dig +short` | [Диагностика DNS](../Networking/dns_deep_dive.md) |
| Эфемерный debug-контейнер, `kubectl cp`, exec в sidecar | — | [Уровень 4: интерактивная отладка](./troubleshooting_overview.md#уровень-4-интерактивная-отладка), [kubectl: отладка](../ToolsUtilities/kubectl_commands.md#отладка-и-поиск-неисправностей) |

## Лучшие практики

- **Серверная фильтрация в приоритете:** `--field-selector` (по фазе, причине, объекту) надёжнее `grep` по выводу — не ломается на изменении формата таблицы.
- **Разрушительные операции с осторожностью:** снятие finalizers и `--force --grace-period=0` — только при мёртвом узле; каноничная последовательность и caveats — в **[Проблемы удаления подов](./Common_Errors/PodTerminating/definitions.md)**.
- **Очистка Evicted-подов:** каноничная форма — `kubectl delete pods --field-selector status.reason=Evicted -A` (см. **[Выселение подов](./Common_Errors/PodEvicted/definitions.md#5-автоматическая-очистка-выселенных-подов)**); парсинг `grep Evicted | awk | xargs` хрупок к пробелам в именах.
- **metrics-server обязателен** для `kubectl top`; без него — Summary API через `get --raw`.

## Дополнительная информация

- Методология диагностики: **[Поиск и устранение неисправностей](./troubleshooting_overview.md)**
- Справочник команд kubectl: **[kubectl_commands](../ToolsUtilities/kubectl_commands.md)**
- Отладочные образы: **[Эфемерные контейнеры](../Base/Pod/ephemeral_containers.md)**
