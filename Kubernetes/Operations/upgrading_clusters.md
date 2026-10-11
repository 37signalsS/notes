# Обновление кластера Kubernetes: Методология и практики

## Определения

**Обновление кластера (Cluster Upgrade)** — процесс поэтапного и контролируемого перевода компонентов Kubernetes (Control Plane, Worker Nodes, Add-ons) на новую минорную или патч-версию с сохранением работоспособности приложений и целостности данных.

**Политика N-2 / N-3** — официальная политика поддержки Kubernetes. Сообщество поддерживает три последние минорные версии. Обновление "через версию" (например, 1.30 → 1.32) официально не поддерживается и сопряжено с высоким риском ошибок в схемах API.

**Breaking changes** — критические изменения в API или логике работы компонентов, которые требуют предварительной модификации манифестов приложений или настроек инфраструктуры перед выполнением обновления.

**Deprecation Policy** — регламентированный процесс вывода устаревших API из эксплуатации. Перед обновлением необходимо убедиться, что все ресурсы (Ingress, Deployment и др.) переведены на актуальные версии API (например, с `extensions/v1beta1` на `networking.k8s.io/v1`).

**Version Skew Policy** — набор правил, определяющих допустимую разницу версий между компонентами кластера (kube-apiserver, kubelet, kubectl, kube-proxy).

## Основные концепции

### Порядок обновления компонентов

Строгое соблюдение очередности критически важно для сохранения стабильности Control Plane и доступности API. Общее правило: **версия клиентских утилит и узлов не должна превышать версию Control Plane**.

**Почему важно сначала обновлять Control Plane?**
Control Plane управляет жизненным циклом всего кластера (планирование, масштабирование, мониторинг). Предварительное обновление гарантирует, что управляющий слой сможет корректно обрабатывать новые версии API, протоколы безопасности и изменения в определениях ресурсов до того, как они появятся на рабочих узлах. Это минимизирует риск несовместимости при взаимодействии API-сервера с обновленными агентами (kubelet).

| Очередность | Компонент | Роль | Принцип обновления |
| :--- | :--- | :--- | :--- |
| 1 | **etcd** | Хранилище кластера | Всегда первым (или одновременно с первым узлом CP). Обязателен снапшот перед началом. |
| 2 | **Control Plane** | API, Scheduler, CM | Обновляются по одному узлу. В HA-кластере сначала обновляется "первичный" мастер. |
| 3 | **Узлы (Worker Nodes)** | Kubelet, Kube-proxy | Последовательно (Rolling update) после стабилизации Control Plane. |
| 4 | **Клиент (kubectl)** | Управление | Обновляется в последнюю очередь или одновременно с CP. Должен быть в пределах ±1 минорной версии. |

### Золотые правила безопасности

1. **Не пропускать минорные версии:** Обновление всегда идет по цепочке (1.31 → 1.32 → 1.33).
2. **Бэкап etcd:** Единственная точка восстановления. Снапшот гарантирует возможность восстановления кластера в случае критического сбоя при обновлении. Сохраняйте его на внешнем носителе.
3. **Дренаж узлов:** Обновление `kubelet` без `kubectl drain` может привести к некорректному завершению подов и потере данных. Детали: [Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md).
4. **Аудит API:** Использование специализированных инструментов (`kubent`, `pluto`) для поиска устаревших ресурсов.
5. **Поэтапность:** Обновление рабочих узлов по одному минимизирует время простоя и позволяет сохранить доступность приложений.

### Совместимость версий (Version Skew Policy)

Актуальные правила для последних версий Kubernetes (1.28+):

* **Kube-apiserver:** В HA-кластере версии экземпляров API-сервера могут отличаться максимум на 1 минорную версию.
* **Kubelet:** Начиная с K8s 1.28, Kubelet может быть на **3 минорные версии старее** API-сервера (например, API 1.31 → Kubelet 1.28). Kubelet **никогда** не может быть новее API-сервера.
* **Kubectl:** Должен быть в пределах ±1 минорной версии от API-сервера.
* **Kube-proxy:** Должен быть той же минорной версии, что и Kubelet, или новее. Он не может быть новее API-сервера и не может отставать от Kubelet более чем на 3 минорные версии (с 1.28+). Рекомендуется держать их версии синхронными.
* **Kubeadm:** Версия утилиты `kubeadm` не должна превышать версию разворачиваемого Control Plane. `kubeadm` может быть на 1 минорную версию старше `kube-apiserver` в момент начала процесса обновления (например, использование `kubeadm 1.31` для обновления кластера до 1.31).

## Практические сценарии

### 1. Подготовка и аудит готовности

#### Аудит API и Release Notes
Изучите раздел "Urgent Upgrade Notes" в официальном репозитории Kubernetes для целевой версии. Рекомендуется проводить аудит **раз в месяц** или перед каждым минорным обновлением.

**Инструмент: Kube No Trouble (kubent)**
Сканирует активный кластер и Helm-релизы на наличие ресурсов, использующих устаревшие API версии.
```bash
# Запуск сканирования текущего контекста (включая Helm 3)
kubent --helm3 --exit-error

# Проверка манифестов в локальной директории
kubent -f ./manifests/
# → list of deprecated/deleted APIs found in the cluster
```

**Инструмент: Pluto**
Специализируется на поиске устаревших версий API в манифестах, Helm-чартах и даже в конфигурациях, которые уже удалены из K8s, но остаются в истории релизов.
```bash
# Проверка установленных Helm-релизов
pluto detect-helm -n default

# Проверка локальных файлов перед деплоем (CI/CD пайплайн)
pluto detect-files -d ./deploy/

# Проверка на соответствие конкретной версии K8s
pluto detect-files -d . --target-versions k8s=v1.32.0
```

#### Проверка здоровья и планов обновления
```bash
# Проверка статуса всех узлов
kubectl get nodes

# Просмотр доступных версий и проверка готовности (только для kubeadm)
kubeadm upgrade plan
```

#### Pre-flight проверки перед обновлением

Перед началом любых операций выполните комплексную проверку состояния кластера. Нарушения, обнаруженные на этом этапе, значительно дешевле исправить, чем после начала обновления.

**1. Здоровье etcd и кворум**
```bash
# Проверка доступности всех членов etcd
k-etcdctl endpoint health --cluster -w table
# → https://10.0.0.10:2379 is healthy: successfully committed and received proposal

# Проверка лидера и членов
k-etcdctl member list -w table
k-etcdctl endpoint status --cluster -w table

# Проверка метрик кворума (Prometheus)
# etcd_server_has_leader == 1
# etcd_server_quota_backend_bytes / etcd_memory_used_bytes < 0.8
```
*Требование:* Все члены healthy, есть лидер, использование диска < 80%.

**2. Целостность снапшота etcd**
```bash
# status читает файл и вычисляет хеш — повреждённый снапшот вызовет ошибку
etcdutl snapshot status /var/lib/kube-backups/etcd-pre-upgrade-$(date +%F).db -w table
# Колонки: hash, revision, total keys, total size, version
```

**3. Сертификаты PKI**
```bash
# Проверка срока действия всех сертификатов кластера
kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   CERTIFICATE AUTHORITY   EXTERNALLY MANAGED
# → admin.conf                 Sep 15, 2026 12:00 UTC   364d                                    no
```
*Требование:* Ни один сертификат не должен истекать в течение следующего Maintenance Window.

**4. Static Pods Control Plane**
```bash
# Все компоненты должны быть в Running
kubectl get pods -n kube-system -l tier=control-plane
# → NAME               READY   STATUS    RESTARTS   AGE
# → kube-apiserver     1/1     Running   0          45d

# Проверка Lease (лидерство)
kubectl get lease -n kube-system -o custom-columns=NAME:.metadata.name,HOLDER:.spec.holderIdentity
```

**5. PodDisruptionBudget для критичных сервисов**
```bash
# Вывод всех PDB и текущего здоровья
kubectl get pdb -A
# → NAMESPACE   NAME   MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → default     myapp  3               <none>             2                     30d

# Проверка, что allowed disruptions > 0 для обслуживания
kubectl get pdb <name> -o jsonpath='{.status.disruptionsAllowed}{"\n"}'
```
*Требование:* Для каждого критичного сервиса `disruptionsAllowed` > 0 или batch size обслуживаемых узлов укладывается в бюджет.

**6. Отсутствие устаревших и удаляемых API**
```bash
# Быстрый скан активного кластера
kubent --helm3 --exit-error

# Проверка Helm-релизов
pluto detect-helm -A
```

**7. Состояние сетевого плагина и CSI**
```bash
# CNI поды должны быть Ready
kubectl get pods -n kube-system -l app=calico -o wide
kubectl get pods -n kube-system -l app=csi-driver -o wide

# Проверка CSI Driver health
kubectl get csidrivers
# → NAME                                           ATTACHREQUIRED   PUBLISHVOLUME   STORAGECAPACITY   ...
# → csi.vsphere.vmware.com                          true             true            false
```

**8. Образы контейнеров (pause image)**
```bash
# Проверка версии pause образа, используемого kubelet
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name} {.status.nodeInfo.runtimeVersion}{"\n"}{end}'
# Убедитесь, что версия containerd/runc совместима с целевой версией K8s.
# См. release notes для минимальной поддерживаемой версии.
```

**9. План изменений (Change Plan)**
- Согласуйте Maintenance Window с командой и стейкхолдерами.
- Убедитесь, что количество одновременно обслуживаемых узлов не превышает `maxUnavailable` в PDB критичных сервисов.
- Подготовьте канал коммуникации (Slack, Statuspage) для информирования о ходе работ.

### 2. Резервное копирование etcd

Выполняется на одном из узлов Control Plane. Снапшот обязателен перед любыми операциями по обновлению, так как etcd хранит все состояние кластера.

```bash
ETCDCTL_API=3 etcdctl snapshot save /var/lib/kube-backups/etcd-pre-upgrade-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Проверка целостности снапшота (обязательно; status читает файл и
# вычисляет хеш — повреждённый снапшот вызовет ошибку)
etcdutl snapshot status /var/lib/kube-backups/etcd-pre-upgrade-$(date +%F).db -w table
# Колонки: hash, revision, total keys, total size, version
```

**Политика хранения снапшотов:**
- Храните копию на внешнем носителе (отдельный сервер, NAS, ленточная библиотека).
- Храните минимум 3 последних снапшота с разными датами.
- Ведите лог создания снапшотов (дата, версия K8s, хэш файла).
- Для автоматизации используйте CronJob на мастере:
  ```bash
  # Пример crontab
  0 2 * * * ETCDCTL_API=3 etcdctl snapshot save /var/lib/kube-backups/etcd-$(date +\%F).db && \
    etcdutl snapshot status /var/lib/kube-backups/etcd-$(date +\%F).db && \
    find /var/lib/kube-backups/ -name "etcd-*.db" -mtime +7 -delete
  ```

**Быстрое восстановление из снапшота (аварийный сценарий):**
```bash
# 1. Остановите Control Plane на всех узлах
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/
sudo mv /etc/kubernetes/manifests/kube-controller-manager.yaml /tmp/
sudo mv /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/

# 2. Восстановите etcd (на первом мастере)
etcdutl snapshot restore /var/lib/kube-backups/etcd-pre-upgrade-2026-08-30.db \
  --data-dir=/var/lib/etcd-restored \
  --name etcd-0 \
  --initial-advertise-peer-urls https://10.0.0.10:2380 \
  --advertise-client-urls https://10.0.0.10:2379

# 3. Обновите --data-dir в манифесте etcd.yaml
# 4. Верните манифесты обратно и дождитесь запуска
sudo mv /tmp/etcd.yaml /etc/kubernetes/manifests/
sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
```
*Подробнее: **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**, **[Стратегии резервного копирования](backup-strategies.md)***.

### 3. Сценарий: Автоматизированное обновление (Kubespray)

Для кластеров, развернутых через Kubespray, рекомендуется использовать встроенные плейбуки.

```bash
# Обновление всего кластера до версии, указанной в переменных (v1.x.x)
ansible-playbook -i inventory/mycluster/hosts.yml upgrade-cluster.yml -e kube_version=v1.32.0
```
*Kubespray автоматически выполняет cordon, drain и обновление каждого узла по очереди.*

### 4. Сценарий: Ручное обновление (на примере kubeadm)

#### Порядок обновления для разных топологий

Порядок обновления зависит от того, как развернут etcd.

**Stacked etcd (etcd на тех же узлах, что и Control Plane — топология по умолчанию для kubeadm):**
1. Обновите первый узел Control Plane (`kubeadm upgrade apply`). Статический под `etcd` обновится автоматически вместе с `kube-apiserver`.
2. Дождитесь стабилизации (`kubectl get pods -n kube-system -l component=etcd`).
3. Перейдите к следующему мастер-узлу.
4. После обновления всех мастер-узлов обновите worker-узлы.

**External etcd (etcd на выделенных узлах):**
1. Обновите узлы внешнего etcd **самыми первыми** (по одному, с проверкой кворума после каждого).
2. Затем обновите первый узел Control Plane.
3. Затем остальные мастер-узлы.
4. Затем worker-узлы.

**Критически важно для HA-кластеров:**
- Никогда не обновляйте более одного мастера одновременно. Потеря кворума etcd = полная недоступность кластера.
- Между обновлением мастер-узлов делайте паузу 2–5 минут для стабилизации лидерства etcd (1–2 смены лидера — нормально, >5 — проблема).
- Если за кластером стоит Load Balancer или VIP, убедитесь, что он корректно определяет готовность (`/readyz`) обновленного узла перед переводом трафика.

Процесс повторяется для каждого узла. Сначала обновляются все узлы Control Plane (строго один за другим, чтобы не потерять кворум etcd), затем Worker-узлы. Если используется внешняя база **etcd** (External etcd topology), её узлы обновляются самыми первыми. В топологии **Stacked etcd** компоненты etcd обновляются вместе с Control Plane при выполнении `kubeadm upgrade apply/node`.

**Шаг 1: Pre-drain проверки и изоляция**
```bash
# Проверка PDB: убедитесь, что бюджет позволяет выселение
kubectl get pdb -A -o wide

# Проверка подов на узле (должны быть только системные и прикладные, подлежащие выселению)
kubectl get pods -o wide --all-namespaces --field-selector spec.nodeName=node-1

# Дренаж узла
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=5m
# → node/node-1 cordoned
# → evicting pod ...
```
*Примечание:* Поды DaemonSet не выселяются `drain`. Они продолжат работу, либо будут остановлены при перезапуске `kubelet`/`containerd`.

**Шаг 2: Обновление пакетов ОС и runtime (опционально, но рекомендуется)**
```bash
# Обновление containerd (если требуется целевой версией K8s)
apt-mark unhold containerd && \
apt-get update && apt-get install -y containerd=1.7.25-0 && \
apt-mark hold containerd

# Перезапуск containerd и проверка версии
systemctl daemon-reload && systemctl restart containerd
ctr version
```
*Почему важно:* Версия containerd/runtim должна соответствовать минимальной требованиям целевой версии Kubernetes (см. Release Notes).

**Шаг 3: Обновление kubeadm**
```bash
apt-mark unhold kubeadm && \
apt-get update && apt-get install -y kubeadm=1.32.0-1.1 && \
apt-mark hold kubeadm
```

**Шаг 4: Применение обновления конфигурации**
```bash
# На первом (primary) мастере (обновляет манифесты apiserver, scheduler, cm и etcd):
sudo kubeadm upgrade apply v1.32.0

# На всех остальных узлах (secondary мастера и воркеры):
sudo kubeadm upgrade node
```
*Валидация:* После `upgrade apply` проверьте, что все static pods перезапустились с новым image tag:
```bash
docker ps | grep kube-apiserver  # или crictl ps для containerd
# → registry.k8s.io/kube-apiserver:v1.32.0
```

**Шаг 5: Обновление бинарных файлов kubelet и kubectl**
```bash
apt-mark unhold kubelet kubectl && \
apt-get update && apt-get install -y kubelet=1.32.0-1.1 kubectl=1.32.0-1.1 && \
apt-mark hold kubelet kubectl
```

**Шаг 6: Перезапуск сервиса и проверка**
```bash
systemctl daemon-reload
systemctl restart kubelet
```
*Ожидание:* Подождите 30–60 секунд, пока kubelet зарегистрирует узел и запустит статические пода (на мастерах) или перейдет в состояние Ready (на воркерах).

**Шаг 7: Валидация API и компонентов**
После рестарта `kubelet` на Control Plane убедитесь, что API отвечает и компоненты поднялись:
```bash
# Проверка доступности API и версии сервера
kubectl version --short

# Проверка статических подов Control Plane
kubectl get pods -n kube-system -l tier=control-plane

# Проверка etcd кворума и лидера
k-etcdctl endpoint health --cluster -w table
k-etcdctl member list -w table

# Проверка Version Skew
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion
# Все узлы должны быть на целевой версии ±1 минорная версия.
```

**Шаг 8: Возврат в работу (Uncordon)**
```bash
kubectl uncordon node-1
# → node/node-1 uncordoned
```

**Шаг 9: Пост-обновление узла**
```bash
# Проверка, что узел Ready и все системные поды запущены
kubectl get node node-1 -o wide
kubectl get pods -n kube-system -o wide --field-selector spec.nodeName=node-1

# Если используется Cluster Autoscaler — убедитесь, что узел не помечен для удаления
kubectl get node node-1 -o jsonpath='{.spec.taints[?(@.key=="node.kubernetes.io/out-of-service")]}'
```

## Сценарий: Промышленное обновление (Production Upgrade Strategy)

Обновление кластера в промышленной среде требует осторожного, поэтапного подхода для минимизации рисков и обеспечения стабильности.

### 1. Подготовка и резервное копирование
До внесения любых изменений обеспечьте наличие актуальных бэкапов и проверку процесса в контролируемой среде.
*   **Автоматическое резервное копирование:** Используйте инструменты уровня **Velero** для бэкапа критических ресурсов и всего состояния кластера (включая etcd).
*   **Зеркалирование Staging:** Промежуточная среда должна максимально точно отражать Production, включая историю обновлений. Если Production прошел путь с v1.28 до v1.31, Staging должен повторить этот же путь. Тестирование обновления в «чистой» среде целевой версии может не выявить накопленных проблем совместимости.

### 2. Проверка ресурсов и аудит API
Убедитесь, что все ресурсы API совместимы с целевой версией.
*   **Удаляемые API:** Проверьте наличие устаревших и удаляемых ресурсов (например, PodSecurityPolicies, старые версии Ingress или NetworkPolicies). Заблаговременное исправление API-манифестов предотвращает сбои после апгрейда API-сервера.
*   **Инструменты:** Используйте `kubent` или `pluto` для автоматизации аудита.

### 3. Пошаговое обновление версий (Minor-by-Minor)
Обновляйте кластер строго по одной минорной версии за раз (например, v1.30 → v1.31).
*   **Почему это важно:** Пропуск версий ведет к несовместимости API, проблемам с конфигурацией и может потребовать сложных ручных исправлений.
*   **Стабильность:** Начинайте с Control Plane. Обновление управляющего слоя первым позволяет кластеру эффективно обрабатывать нагрузки с новыми изменениями API.

### 4. Обновление приложений и зависимостей
После стабилизации инфраструктуры переходите к обновлению прикладного стека.
*   **Rolling Update:** Используйте чередующиеся обновления (`RollingUpdate`) для приложений. Это позволяет заменять поды один за другим, проверяя стабильность новой версии в реальном времени без прерывания обслуживания.
    ```bash
    kubectl set image deployment/my-app my-container=my-app:v2
    ```
*   **ConfigMaps и Secrets:** При изменении конфигураций или секретов может потребоваться **Rollout Restart** подов для отражения изменений, если приложение не поддерживает Hot Reload.
*   **Внешние зависимости:** Убедитесь, что версии баз данных, сторонних API и других сервисов совместимы с новой версией Kubernetes и изменениями в приложении.

### 5. Обновление аддонов (Cluster Add-ons)

После стабилизации инфраструктуры и узлов необходимо убедиться, что все системные надстройки совместимы с новой версией Kubernetes.

**Порядок обновления (рекомендуемый):**
1. **Сначала CRDs и вебхуки ( validating/mutating admission webhooks )**: Убедитесь, что сертификаты CA вебхуков действительны и не блокируют создание ресурсов с новыми версиями API.
2. **CoreDNS**: Обновите Deployment CoreDNS. Проверьте, что сервис `kube-dns` отвечает.
3. **Kube-proxy**: Обычно обновляется автоматически как демон (DaemonSet). Проверьте версии на всех узлах.
4. **CNI плагин** (Calico, Cilium, Flannel и др.): Это самый критичный аддон. Обновите его раньше прикладных нагрузок. После обновления проверьте:
   ```bash
   # Проверка сетевой связности
   kubectl run nettest --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default
   kubectl exec -ti nettest -- ping -c3 <pod-cidr-gateway>
   ```
5. **CSI drivers и StorageClasses**: Убедитесь, что CSI sidecar контейнеры (external-provisioner, external-attacher, external-snapshotter) совместимы с целевой версией. Проверьте `csidrivers` и `storageclasses`.
6. **Metrics-server, Dashboard, другие аддоны**: Обновляйте по одному, проверяя метрики и работу после каждого.

**Helm-чарты:** Всегда начинайте с обновления Helm-чартов приложений и системных компонентов. Это гарантирует, что манифесты используют актуальные возможности кластера и корректные версии API.
*   **Порядок:** Обновляйте аддоны по одному, проверяя работоспособность каждого на Staging перед Production.

### 6. Мониторинг стабильности

Процесс обновления не заканчивается на `uncordon`.
*   **Длительность:** Отслеживайте показатели работоспособности кластера, логи и производительность приложений **минимум одну неделю** после апгрейда.
*   **Фокус:** Особое внимание уделяйте сетевому уровню. Аддоны (особенно CNI) могут создавать трудноуловимые проблемы, проявляющиеся только под нагрузкой.
*   **Инструменты:** Используйте Prometheus, Grafana или корпоративные системы мониторинга SLO/SLI для отслеживания метрик и выявления скрытых аномалий.

### 6.5. Пост-апгрейд валидация (Post-Upgrade Validation)

После обновления всего кластера выполните обязательный чек-лист:

```bash
# 1. Версии узлов
kubectl get nodes -o wide
# → Все узлы должны показать целевую версию

# 2. Статус всех подов Control Plane
kubectl get pods -n kube-system -l tier=control-plane
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl get pods -n kube-system -l app=csi-driver

# 3. Здоровье etcd
k-etcdctl endpoint health --cluster -w table
k-etcdctl endpoint status --cluster -w table

# 4. Сертификаты
kubeadm certs check-expiration

# 5. Сетевая связность (Network Policy / CNI)
kubectl run nettest --image=busybox --rm -it --restart=Never -- wget -qO- http://kubernetes.default

# 6. Проверка Storage
kubectl get storageclass
kubectl get csidrivers
kubectl get volumeattachment

# 7. Аудит API (повторный)
kubent --helm3 --exit-error
pluto detect-helm -A

# 8. Метрики API-сервера (APF, latency, errors)
kubectl get --raw /metrics | grep apiserver
```

### 7. Массовое обновление рабочих узлов (Batch Upgrade)

При обновлении пула worker-узлов применяйте подход "batched rolling upgrade" с учетом PDB:

**Расчет безопасного размера партии (Batch Size):**
```text
Batch Size = min(количество_узлов_в_пуле, floor((Общее_количество_под_of_сервис - PDB.minAvailable) / Реплик_на_узел))
```
На практике часто используют batch size = 1 для критичных сервисов и batch size = 2–3 для менее критичных, если PDB позволяет.

**Алгоритм:**
1. Определите размер пула и PDB для критических сервисов.
2. Соберите第一批 (batch) из N узлов.
3. Выполните `cordon` + `drain` на каждом узле в партии последовательно (один за другим).
4. Выполните обновление пакетов и `kubeadm upgrade node`.
5. Валидируйте узел (Ready, системные поды).
6. `uncordon`.
7. Перейдите к следующему батчу.

*Связь с node_maintenance.md:* Детали команды `drain`, флаги и NodeMaintenance API описаны в **[Обслуживании узлов (Cordon/Drain)](../Operations/node_maintenance.md)**.

### 8. Стратегия обновления по средам
Поэтапное обновление — лучший способ минимизировать риски в масштабе организации.
*   **Последовательность:** Сначала обновляются непроизводственные кластеры (Dev → Test/QA), затем Production.
*   **Зеркалирование:** Убедитесь, что процесс верифицирован на Staging в условиях, максимально приближенных к рабочим, прежде чем приступать к Production.

### 8. Планирование следующего обновления
Обновление кластера — непрерывный процесс.
*   **Технический долг:** Планируйте переход к следующей минорной версии (например, v1.31 → v1.32) сразу после стабилизации текущей.
*   **Безопасность:** Регулярные небольшие обновления предотвращают накопление критических уязвимостей и упрощают процесс миграции в будущем.

## Регламент технического обслуживания

### Стратегия отката и аварийного восстановления

`kubeadm` не поддерживает команду `rollback`. Единственный путь назад — комбинация восстановления из снапшота etcd и переустановки пакетов.

**Уровни отката:**

| Уровень | Ситуация | Действие |
| :--- | :--- | :--- |
| **Уровень 1: Один узел не стартовал** | После обновления узел в `NotReady` | Откатите пакеты на узеле: `apt-get install kubelet=1.31.0-1.1 kubeadm=1.31.0-1.1 kubectl=1.31.0-1.1`. Удалите узел из кластера (`kubectl delete node`), исправьте и повторите присоединение. |
| **Уровень 2: Control Plane нестабилен** | API отвечает с ошибками, поды CP в CrashLoop | Если кворум etcd сохранен — откатите манифесты CP к старой версии (restore из git/config management). Если кворум потерян — переходите к Уровню 3. |
| **Уровень 3: Потеря кворума / полный отказ** | API не доступен, etcd потерял лидера | Восстановление из снапшота etcd (см. раздел "Резервное копирование etcd"). При крайней необходимости используйте `--force-new-cluster` — он сохраняет данные из `data-dir` выжившего члена, но panic'нет при живых узлах старого кластера (риск двух независимых кластеров). См. [Аварийное восстановление etcd](../../etcd/emergency_recovery.md). |

**Подготовка к откату (до начала обновления):**
- Имейте готовый playbook с командами отката пакетов.
- Если используете Ansible/Terraform — зафиксируйте состояние "до обновления" (tags, branch).
- Назначьте ответственного за принятие решения об откате (rollback owner).

**Важно:** Перед восстановлением из снапшота убедитесь, что все новые изменения в кластере (созданные после снапшота) документированы, так как они будут потеряны.

Для обеспечения стабильности и безопасности кластера рекомендуется придерживаться следующего графика выполнения регламентных работ.

| Задача | Периодичность | Инструменты | Цель |
| :--- | :--- | :--- | :--- |
| **Аудит API** | Раз в месяц | `kubent`, `pluto` | Поиск устаревших API перед обновлением. |
| **Бэкап etcd** | Ежедневно / Перед изменениями | `etcdctl` | Обеспечение возможности восстановления состояния кластера. |
| **Проверка сертификатов** | Раз в квартал | `kubeadm certs check-expiration` | Предотвращение остановки кластера из-за истечения SSL. |
| **Аудит ресурсов (Limits)** | Раз в месяц | `kubectl top`, `goldilocks` | Оптимизация запросов и лимитов (Requests/Limits). |

## Диагностика и устранение проблем

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Node NotReady** | `kubectl describe node <node>` | Проверить логи `journalctl -u kubelet`. Возможны ошибки в новых параметрах конфигурации или сертификатах. |
| **Pod CrashLoopBackOff** | `kubectl logs <pod>` | Проверить, не использует ли приложение API, удаленное в этой версии. Проверить совместимость CNI плагина. |
| **API Server Timeout** | `curl -k https://localhost:6443/healthz` | Проверить статус статических подов в `/etc/kubernetes/manifests/`. Проверить кворум etcd. |
| **Drain Failure** | Ошибка таймаута при выселении | Проверить [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md). Использовать `--force` для подов без контроллеров. |
| **Cert Expired** | Ошибка TLS в логах компонентов | `kubeadm certs check-expiration`. Обновление через `kubeadm upgrade` автоматически продлевает сертификаты. |
| **APF Throttling** | `kubectl get --raw /metrics | grep apiserver_requested_deprecated_instances` | Проверьте, не попал ли клиент под лимит APF. Увеличьте `--max-requests-inflight` или уберите deprecated clients. |
| **CNI/NetworkPolicy Broken** | `kubectl exec -ti <pod> -- ping <other-pod>` | CNI плагин несовместим с новой версией. Откатите CNI, проверьте release notes, обновите CSI/CNI sidecars. |
| **CSI Driver Unhealthy** | `kubectl get pods -n kube-system -l app=csi-driver` | Проверьте, что CSI sidecar контейнеры (external-provisioner и др.) совместимы с K8s vX.Y. Обновите CSI driver chart. |
| **Pause Image Mismatch** | `kubectl get nodes -o jsonpath='{range .items[*]}{.status.nodeInfo.runtimeVersion}{"\n"}{end}'` | Версия containerd/runc слишком старая. Обновите runtime до минимальной требуемой версии (см. Release Notes). |
| **Webhook Blocking** | `kubectl get events --field-selector reason=FailedCreate` | Admission webhook возвращает ошибку для новых API версий. Обновите вебхук или добавьте исключение (`failurePolicy: Ignore`). |

## Рекомендации (Best Practices)

* **Один узел за раз (Serial Upgrades):** Никогда не обновляйте более одного узла Control Plane одновременно, чтобы избежать потери кворума etcd.
* **Инфраструктура как код (IaC):** Всегда фиксируйте версии Kubernetes в ваших Ansible-плейбуках или Terraform-конфигурациях.
* **PDB-aware batch size:** При массовом обновлении рабочих узлов рассчитывайте размер партии так, чтобы `disruptionsAllowed` в PDB критичных сервисов не исчерпывался.
* **Pause image pinning:** Фиксируйте версии pause образа в kubelet configuration (`--pod-infra-container-image`), особенно при использовании внутреннего registry.
* **Admission webhooks:** Перед обновлением проверьте, что все validating/mutating webhooks совместимы с целевой версией K8s. Используйте `failurePolicy: Ignore` для некритичных вебхуков во время апгрейда.
* **API Priority and Fairness (APF):** После обновления следите за метрикой `apiserver_requested_deprecated_instances` и настройками `--max-requests-inflight`, чтобы избежать троттлинга легитимных клиентов.
* **Мониторинг метрик:** Во время обновления следите за:
    * `apiserver_request_duration_seconds` (время ответа API).
    * `etcd_server_has_leader` (стабильность кворума).
    * `kubelet_pleg_relist_duration_seconds` (скорость обнаружения изменений).
* **План отката:** Помните, что `kubeadm` не поддерживает команду rollback. Единственный путь назад — удаление узлов, переустановка пакетов старой версии и восстановление etcd из снапшота.
* **Обновление сертификатов:** Проверяйте статус сертификатов перед обновлением. `kubeadm upgrade` обновит их только если они управляются им напрямую.
* **Согласование Change Window:** Обновляйте кластер в заранее согласованное окно, когда нагрузка минимальна, а команда дежурства готова к реагированию.

## Дополнительная информация

### Связанные темы

* [Управление сертификатами](certificate_management.md) — ручное продление и ротация.
* [Обслуживание узлов](node_maintenance.md) — детальное описание процессов Cordon и Drain, NodeMaintenance API.
* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — настройка бюджетов доступности и взаимодействие с drain.
* [Высокая доступность в Kubernetes](../Base/high_availability.md) — архитектура HA-кластеров, кворум etcd, лидерство.
* [etcd: операции и обслуживание](../Concepts/etcd_operations.md) — снапшоты, восстановление, обновление etcd.
* [Kubespray: Управление кластером](../Installation/Kubespray/cluster_management.md) — детали автоматизации.
* [RKE: Управление](../Installation/RKE/rke_management_scenarios.md) — специфика обновления в Rancher.
* [Стратегии резервного копирования](backup-strategies.md) — общие принципы бэкапа и DR для Kubernetes.
