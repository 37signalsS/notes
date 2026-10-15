# Команды kubectl

## Определения

**kubectl** — CLI для управления Kubernetes-кластером через API-сервер. Установка, совместимость версий и переменные окружения — в [Установка kubectl](../Installation/kubectl_installation.md).

Ниже — справочник из 73 команд, сгруппированных по категориям. Плейсхолдеры `<name>`, `<ns>`, `<pod>` заменяются на реальные значения.

## Справочник команд

### Pods

#### Список всех подов во всех неймспейсах

Все поды с расположением на нодах и IP-адресами.

```bash
kubectl get pods -A -o wide
```

#### Описание пода

Подробная информация: события, условия, монтирование томов.

```bash
kubectl describe pod <name> -n <ns>
```

#### Войти в под

Интерактивная оболочка внутри работающего контейнера.

```bash
kubectl exec -it <pod> -n <ns> -- bash
```

#### Принудительное удаление зависшего пода

Удалить под в состоянии Terminating немедленно (используйте с осторожностью).

```bash
kubectl delete pod <name> -n <ns> --grace-period=0 --force
```

#### Ресурс с кастомными колонками

Вывести только нужные поля без jq.

```bash
kubectl get pods -n <ns> -o custom-columns='NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase'
```

#### Запустить разовый под

Временный под для отладки; удаляется при выходе.

```bash
kubectl run tmp --image=nicolaka/netshoot -it --rm --restart=Never -n <ns> -- bash
```

#### Watch статуса подов

Обновление в реальном времени при изменении статусов.

```bash
kubectl get pods -n <ns> -w
```

#### Поды по CPU

Использование CPU по всем неймспейсам, отсортировано.

```bash
kubectl top pods -A --sort-by=cpu
```

#### Удалить все поды в неймспейсе

Форс-рекреация всех подов — удобно после смены ConfigMap.

```bash
kubectl delete pods --all -n <ns>
```

#### Дамп всех подов в YAML

Резервная копия/инспекция всех подов неймспейса в YAML.

```bash
kubectl get pods -n <ns> -o yaml > pods-dump.yaml
```

#### Все образы контейнеров в кластере

Перечислить все образы контейнеров, запущенных в кластере.

```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .spec.containers[*]}{.image}{"\n"}{end}{end}'
```

#### Ждать готовности пода

Заблокировать до готовности подов или таймаута.

```bash
kubectl wait pod -l app=<label> -n <ns> --for=condition=Ready --timeout=120s
```

#### Выполнить команду во всех подах

Выполнить команду в каждом поде с нужным label selector.

```bash
kubectl get pods -n <ns> -l app=<label> -o name | xargs -I{} kubectl exec {} -n <ns> -- <cmd>
```

#### Топология spread constraints

Проверить topologySpreadConstraints пода.

```bash
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.topologySpreadConstraints}'
```

#### Сортировать поды по числу рестартов

Вывести наиболее перезапускаемые поды, чтобы быстро поймать crashloop.

```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}' | sort -k3 -rn | head
```

#### Найти все упавшие поды по кластеру

Список подов в фазе Failed по всем неймспейсам для очистки или разбора.

```bash
kubectl get pods -A --field-selector status.phase=Failed
```

#### Копирование файла из пода

Извлечь файл из работающего контейнера.

```bash
kubectl cp <ns>/<pod>:/remote/path ./local-path
```

### Логи

#### Следить за логами пода

Потоковые логи в реальном времени; добавьте `-c <container>` для мульти-контейнерных подов.

```bash
kubectl logs -f <pod> -n <ns>
```

#### Логи предыдущего контейнера

Логи последнего упавшего или перезапущенного экземпляра контейнера.

```bash
kubectl logs <pod> --previous -n <ns>
```

### Deployments и раскатка

#### Следить за статусом rollout

Блокировать до завершения деплоя или таймаута (используется в CI).

```bash
kubectl rollout status deployment/<name> -n <ns>
```

#### Откат деплоймента

Вернуться к предыдущей ревизии.

```bash
kubectl rollout undo deployment/<name> -n <ns>
```

#### Масштабирование деплоймента

Немедленно изменить количество реплик.

```bash
kubectl scale deployment/<name> --replicas=3 -n <ns>
```

#### Редактировать ресурс в кластере

Открыть ресурс в `$EDITOR`; изменения применяются при сохранении.

```bash
kubectl edit deployment/<name> -n <ns>
```

#### Patch поля ресурса

Изменить поле ресурса без редактирования манифеста.

```bash
kubectl patch deployment <name> -n <ns> -p '{"spec":{"replicas":2}}'
```

#### Обновить образ деплоймента

Обновить образ контейнера без редактирования YAML.

```bash
kubectl set image deployment/<name> <container>=image:tag -n <ns>
```

#### История деплоев

Все ревизии с причиной изменения.

```bash
kubectl rollout history deployment/<name> -n <ns>
```

#### Rolling restart деплоймента

Перезапустить поды по одному без простоя.

```bash
kubectl rollout restart deployment/<name> -n <ns>
```

#### Задать requests/limits

Обновить requests и limits деплоймента без правки YAML.

```bash
kubectl set resources deployment/<name> -c <container> --requests=cpu=100m,memory=128Mi --limits=cpu=500m,memory=512Mi -n <ns>
```

#### Статус HPA

HPA — текущие/желаемые реплики и метрики.

```bash
kubectl get hpa -A
```

#### Статус PodDisruptionBudget

Показать min-available и текущее число здоровых подов.

```bash
kubectl get pdb -A
```

#### Приостановить и возобновить раскатку

Накопить несколько правок без отдельных раскаток, затем применить всё разом.

```bash
kubectl rollout pause deploy/<name> -n <ns>; kubectl rollout resume deploy/<name> -n <ns>
```

### Ноды

#### Cordon ноды

Пометить ноду как неналиняющую — новые поды сюда не попадают.

```bash
kubectl cordon <node>
```

#### Drain ноды

Аккуратно вытеснить все поды перед обслуживанием.

```bash
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

#### Добавить лейбл к ресурсу

Добавить или изменить лейбл на любом ресурсе.

```bash
kubectl label node <node> role=worker --overwrite
```

#### Добавить taint на ноду

Запретить размещение подов без соответствующего toleration.

```bash
kubectl taint nodes <node> key=value:NoSchedule
```

#### Снять taint с ноды

Снять taint — поставить тире в конце.

```bash
kubectl taint nodes <node> key=value:NoSchedule-
```

#### Лейблы нод

Все лейблы, назначенные на каждую ноду.

```bash
kubectl get nodes --show-labels
```

#### Разблокировать ноду

Разрешить планирование на ранее заблокированной ноде.

```bash
kubectl uncordon <node>
```

#### Условия ноды

Все условия каждой ноды (Ready, MemoryPressure, DiskPressure).

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{": "}{range .status.conditions[*]}{.type}={.status},{" "}{end}{"\n"}{end}'
```

#### Сравнить allocatable и capacity нод

Показать зарезервированный оверхед по нодам; разница = резервы kube/system.

```bash
kubectl get nodes -o json | jq -r '.items[] | {node:.metadata.name, capCPU:.status.capacity.cpu, allocCPU:.status.allocatable.cpu, capMem:.status.capacity.memory, allocMem:.status.allocatable.memory}'
```

### Конфигурация и манифесты

#### Проверка манифеста (server-side dry-run)

Валидация манифеста через живой API без применения изменений.

```bash
kubectl apply --server-side --dry-run=server -f file.yaml
```

#### Экспорт ресурса в YAML

Текущее состояние без служебных полей; удобен как базовый шаблон.

```bash
kubectl get deployment/<name> -n <ns> -o yaml
```

#### Создать неймспейс

Создать новый неймспейс; идемпотентно через `--dry-run=client | apply`.

```bash
kubectl create namespace <ns>
```

#### Добавить аннотацию к ресурсу

Добавить/обновить аннотацию; `--overwrite` заменяет существующее значение.

```bash
kubectl annotate pod <pod> -n <ns> key=value --overwrite
```

#### Квоты ресурсов неймспейса

Использованные vs жёсткие лимиты CPU, памяти, объектов в неймспейсе.

```bash
kubectl describe resourcequota -n <ns>
```

#### LimitRange неймспейса

Дефолтные и максимальные ресурсные лимиты подов в неймспейсе.

```bash
kubectl describe limitrange -n <ns>
```

#### Все CRD в кластере

Все Custom Resource Definitions, отсортированные по времени создания.

```bash
kubectl get crds --sort-by='.metadata.creationTimestamp'
```

#### Apply с удалением лишнего

Применить манифесты и удалить устаревшие объекты по label selector.

```bash
kubectl apply -f ./dir/ --prune -l app=<label> -n <ns>
```

#### Diff живого vs локального

Показать, что изменится при применении этого манифеста.

```bash
kubectl diff -f file.yaml
```

#### Создать токен ServiceAccount

Сгенерировать краткосрочный bound-токен ServiceAccount.

```bash
kubectl create token <sa-name> -n <ns> --duration=1h
```

#### Переключить kubeconfig контекст

Переключить активный контекст кластера.

```bash
kubectl config use-context <context>
```

#### Список kubeconfig контекстов

Все контексты в текущем kubeconfig.

```bash
kubectl config get-contexts
```

#### Объединить kubeconfig файлы

Объединить несколько kubeconfig файлов в один.

```bash
KUBECONFIG=~/.kube/config:~/.kube/cluster2.yaml kubectl config view --flatten > ~/.kube/merged.yaml
```

#### Дефолтный неймспейс контекста

Не нужно добавлять `-n` в каждую команду для этого контекста.

```bash
kubectl config set-context --current --namespace=<ns>
```

#### Запустить CronJob вручную

Немедленно запустить CronJob как разовый Job.

```bash
kubectl create job --from=cronjob/<name> manual-run -n <ns>
```

#### Показать последнюю применённую конфигурацию

Показать аннотацию last-applied-configuration; сравнить намерение с реальным состоянием.

```bash
kubectl apply view-last-applied deploy/<name> -n <ns> -o yaml
```

#### Рекурсивно раскрыть спецификацию Deployment

Вывести полное дерево вложенных полей спецификации ресурса; удобно искать допустимые поля.

```bash
kubectl explain deploy.spec --recursive | less
```

#### ConfigMap из env-file с JSON-патчем

Собрать CM из файла KEY=VALUE и JSON-патчем добавить его в envFrom контейнера.

```bash
kubectl create configmap <name> --from-env-file=app.env -n <ns> --dry-run=client -o yaml | kubectl apply -f -; kubectl patch deploy/<name> -n <ns> --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/envFrom/-","value":{"configMapRef":{"name":"<name>"}}}]'
```

### Сеть

#### Проброс порта сервиса

Туннелирование порта кластерного сервиса на localhost.

```bash
kubectl port-forward svc/<name> 8080:80 -n <ns>
```

#### Endpoints сервиса

Pod IP-адреса за Service — диагностика несоответствия selector.

```bash
kubectl get endpoints <svc> -n <ns>
```

#### Проверить срок сертификата

Статус и дата истечения сертификатов cert-manager.

```bash
kubectl get certificate -A -o wide
```

#### Список Ingress

Все Ingress-ресурсы с хостами и адресами.

```bash
kubectl get ingress -A
```

### RBAC и права

#### Проверка прав RBAC

Проверить, что имеет право делать ServiceAccount.

```bash
kubectl auth can-i list pods --as=system:serviceaccount:<ns>:<sa> -n <ns>
```

#### Аудит прав — кто что может

Все разрешения текущего пользователя в неймспейсе.

```bash
kubectl auth can-i --list -n <ns>
```

#### Имперсонация пользователя и группы

Проверить RBAC от чужого имени без его kubeconfig; нужен verb `impersonate`.

```bash
kubectl auth can-i list secrets -n <ns> --as=<name> --as-group=system:serviceaccounts
```

### Отладка и поиск неисправностей

#### События кластера по времени

Последние события кластера, сначала старые — удобно при post-incident разборе.

```bash
kubectl get events -A --sort-by='.lastTimestamp'
```

#### Предупреждающие события по всем неймспейсам

Предупреждения по всему кластеру, новые в конце; быстрая сортировка проблемных нагрузок.

```bash
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp
```

#### Информация о кластере

API server и CoreDNS endpoints кластера.

```bash
kubectl cluster-info
```

#### Снять метрики эндпоинта apiserver

Получить сырые метрики Prometheus с apiserver без стека мониторинга.

```bash
kubectl get --raw /metrics | grep apiserver_request_total
```

#### Проверить здоровье etcd через apiserver

Проверить доступность etcd через эндпоинт здоровья apiserver.

```bash
kubectl get --raw '/healthz/etcd?verbose'
```

#### Метрики нод из API metrics.k8s.io

Сырое потребление нод из metrics API в обход форматирования `kubectl top`.

```bash
kubectl get --raw '/apis/metrics.k8s.io/v1beta1/nodes' | jq '.items[] | {name:.metadata.name, cpu:.usage.cpu, mem:.usage.memory}'
```

#### Эфемерная отладочная копия с общими PID

Клонировать под с отладочным контейнером в общем PID-namespace; оригинал не трогается.

```bash
kubectl debug <pod> -n <ns> --copy-to=<pod>-dbg --share-processes --image=nicolaka/netshoot -- sleep infinity
```

#### Ждать по условию jsonpath

Блокировать CI до появления внешнего IP у Service; работает по любому полю jsonpath.

```bash
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress[0].ip}' svc/<name> -n <ns> --timeout=120s
```

## Дополнительная информация

- Источник: [cheatsheet.antonnovikov.com/kubectl](https://cheatsheet.antonnovikov.com/ru/kubectl/)
- Установка и совместимость версий: [Установка kubectl](../Installation/kubectl_installation.md)
- Контексты и kubeconfig: [kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)
- Отладка кластера: [Поиск неисправностей](../Troubleshooting/troubleshooting_overview.md)
