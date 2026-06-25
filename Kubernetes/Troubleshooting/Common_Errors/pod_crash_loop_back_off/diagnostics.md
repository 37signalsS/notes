# Поиск и устранение неисправностей: Диагностика `CrashLoopBackOff`

## Определения

**Диагностика CrashLoopBackOff** — последовательный процесс выявления причин циклического перезапуска контейнеров. Основная задача диагностики — разделить проблемы инфраструктуры Kubernetes (права доступа, лимиты, сеть) и проблемы самого приложения (ошибки кода, конфигурации).

Общие понятия и архитектура цикла перезапуска описаны в файле:
> **[Определения и концепции CrashLoopBackOff](./definitions_and_concepts.md)**

## Основные концепции диагностики

Для эффективного поиска причин используются три уровня анализа:

1. **Уровень событий (Events):** позволяет увидеть проблемы на этапе подготовки (монтирование томов, планирование, права доступа).
2. **Уровень состояния (Status):** предоставляет коды завершения процесса и историю перезапусков.
3. **Уровень приложения (Logs):** дает доступ к выводу самого приложения непосредственно перед падением.

### Расшифровка ключевых терминов

- **API (Application Programming Interface)** — программный интерфейс для взаимодействия с компонентами кластера.
- **RBAC (Role-Based Access Control)** — модель управления доступом на основе ролей.
- **DNS (Domain Name System)** — система получения IP-адресов по именам сервисов.
- **SVC (Service)** — абстракция Kubernetes для обеспечения сетевой связности подов.

## Практические сценарии

### Пошаговый алгоритм диагностики

#### Шаг 1: Анализ состояния и событий Pod

Первым делом необходимо проверить статус и историю событий через `describe`.

```bash
kubectl describe pod <pod-name>
```

**Ожидаемый вывод (фрагмент при ошибке):**

```text
State:          Waiting
  Reason:       CrashLoopBackOff
Last State:     Terminated
  Reason:       Error
  Exit Code:    1
Restart Count:  5
Events:
  Type     Reason   Age                From               Message
  ----     ------   ----               ----               -------
  Normal   Created  10m (x5 over 12m)  kubelet            Created container
  Warning  BackOff  10m (x5 over 12m)  kubelet            Back-off restarting failed container
```

#### Шаг 2: Просмотр логов предыдущей итерации

Если контейнер падает сразу после старта, стандартная команда `logs` может быть пустой. Необходимо смотреть логи *предыдущего* запуска.

```bash
# Просмотр логов падения предыдущей инстанции (критически важно)
kubectl logs <pod-name> --previous

# Для подов с несколькими контейнерами
kubectl logs <pod-name> -c <container-name> --previous
```

#### Шаг 3: Проверка конфигурации и окружения

Часто причиной является отсутствие необходимых ConfigMap, Secret или переменных окружения.

```bash
# Проверка наличия и содержимого ConfigMap
kubectl get configmap <configmap-name> -o yaml

# Проверка Secret (просмотр ключей без декодирования)
kubectl get secret <secret-name> -o yaml
```

#### Шаг 4: Проверка сетевых зависимостей и DNS

Если приложение падает из-за недоступности базы данных или внешнего API, проверьте разрешение имен.

```bash
# Проверка DNS-имени внутри кластера через временный под
kubectl run debug --rm -it --image=busybox --restart=Never -- nslookup <service-name>.<namespace>.svc.cluster.local

# → Ожидаемый ответ:
# Server:    10.96.0.10
# Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local
# Name:      <service-name>...
# Address 1: 10.101.5.111
```

#### Шаг 5: Проверка лимитов памяти и OOMKilled

Если в `Events` указан `OOMKilled` (exit code 137), контейнеру не хватает памяти.

```bash
# Проверка лимитов пода
kubectl get pod <pod-name> -o jsonpath='{range .spec.containers[*]}{.resources.limits.memory}{"\n"}{end}'
```

Решение: увеличить `resources.limits.memory` или исправить утечку памяти.

#### Шаг 6: Отладка без перезапусков (restartPolicy: Never)

Создайте под с тем же образом и `restartPolicy: Never` — он останется в состоянии `Error` после падения, не перезапускаясь, и можно будет войти через `kubectl exec`.

```bash
kubectl run debug --image=my-app:latest --restart=Never -- <command>
kubectl exec -it debug -- sh
```

Альтернатива: изменить стратегию развертывания существующего пода, подменив entrypoint на `sleep 3600`:

```bash
kubectl patch deployment <name> --patch '{"spec":{"template":{"spec":{"containers":[{"name":"app","command":["sleep","3600"]}]}}}}'
```

#### Шаг 7: Проверка прав доступа (RBAC)

Если приложение обращается к Kubernetes API, оно должно использовать ServiceAccount (SA) с соответствующими правами.

```bash
# 1. Узнать имя ServiceAccount пода
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# 2. Проверить возможность выполнения действия (Self-Subject Access Review)
kubectl auth can-i get secrets --as=system:serviceaccount:<namespace>:<sa-name>
# → Result: yes / no
```

## Дополнительная информация

### Инструменты автоматизации

Для массовой диагностики `CrashLoopBackOff` рекомендуется использовать инструменты:

- **[Kubetail](../../ToolsUtilities/kubetail.md)** — одновременный просмотр логов нескольких подов.
- **Stern** — продвинутый стриминг логов по регулярным выражениям.

---

### Ссылки

- **[Распространенные решения](./common_cases_and_solutions.md)** — разбор типовых кейсов и их исправление.
- **[Обзор диагностики Kubernetes](../../troubleshooting_overview.md)** — общие принципы поиска неисправностей.
