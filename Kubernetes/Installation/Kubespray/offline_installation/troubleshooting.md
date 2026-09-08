# Kubespray: Offline-установка — Устранение неполадок

## Определения

**Диагностика (Troubleshooting)** — процесс идентификации, анализа и устранения технических неисправностей, возникающих на различных этапах развёртывания и эксплуатации кластера в закрытом контуре. В offline-среде каждый сбой имеет усиленное воздействие: отсутствие доступа к интернету превращает мелкие недочеты в блокирующие ошибки.

**Конфликт Digest** — несовпадение контрольной суммы образа **SHA (Secure Hash Algorithm)** при его переносе между реестрами. Поскольку Kubespray по умолчанию проверяет целостность через digest, любые изменения при push в локальный Harbor могут блокировать запуск. Digest может измениться при пересоздании образа (`docker build`), миграции через `docker save/load`, или при ручном тегировании.

**Эскалация сбоев (Blast Radius)** — характерная для offline-сред особенность: отсутствие fallback-механизмов (публичные реестры, NTP-серверы, DNS-резолверы) приводит к тому, что единичный сбой одного компонента (например, Harbor) парализует весь кластер.

**Инвентарь (Inventory)** — файл конфигурации Ansible (`inventory.ini`), определяющий список целевых узлов и их группировку (master, node). В offline-режиме IP-адреса должны точно соответствовать адресам закрытого контура, а не.pc-inet.

Общие определения ошибок Kubernetes приведены в **[глоссарии ошибок подов](../../../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)**.

---

## Основные концепции

### Специфика диагностики в закрытом контуре

В изолированной среде отсутствие доступа к интернету превращает мелкие недочеты (например, забытый образ) в блокирующие ошибки. Диагностика строится на принципе **«от локального к удалённому»**: сначала проверяется локальная инфраструктура (containerd, disk, NTP), затем сетевая связность, и только потом — компоненты Kubernetes.

**Ключевые зоны риска:**
- **Доверие TLS:** отсутствие корневого сертификата Harbor на узлах кластера. Каждый узел должен доверять CA, подписавшему сертификат Harbor.
- **Синхронизация времени:** рассинхрон NTP приводит к невалидности сертификатов K8s и Harbor. Даже расхождение в несколько секунд может сделать TLS-соединения невозможными.
- **Сетевая инкапсуляция:** проблемы с MTU при использовании VXLAN/Geneve поверх виртуальных сетей (VMware/Proxmox). Инкапсуляция Cilium добавляет заголовки, которые могут превысить MTU физического интерфейса.
- **Python окружение:** отсутствие системных библиотек (например, `python3-apt`) внутри venv на pc-inet. Kubespray использует модули Ansible, которые зависят от системных пакетов Python.
- **Дисковое пространство:** недостаток места на узлах приводит к сбоюkubelet (DiskPressure) и невозможности загрузки образов.
- **Сервисы реестра:** Harbor — единственная точка доступа к образам. Его недоступность полностью блокирует установку и обновление.

### Порядок диагностики

При возникновении ошибки следуйте последовательности:

1. **Узел:** проверьте состояниеkubelet, containerd и дискового пространства на проблемном узле.
2. **Сеть:** убедитесь в связности между узлами и доступности Harbor.
3. **Реестр:** проверьте наличие образа в Harbor и корректность настроек containerd.
4. **Компоненты Kubernetes:** анализируйте логи cụного компонента (etcd, apiserver, Cilium).

---

## Практические сценарии

### 1. Ошибки ImagePullBackOff (Реестр и Сертификаты)

Самая распространенная группа ошибок в offline-режиме. Подробная общая информация об ошибках загрузки образов приведена в разделе **[Ошибки загрузки образов: Air-gapped кластеры](../../../../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)**.

**Симптом:** `kubectl describe pod` показывает `x509: certificate signed by unknown authority`.
**Причина:** CA-сертификат Harbor не добавлен в доверенное хранилище узла. Containerd при попытке pull проверяет цепочку сертификатов и отклоняет соединение.
**Решение:**
1. Скопируйте CA-сертификат Harbor на все узлы:
   ```bash
   sudo cp harbor-ca.crt /usr/local/share/ca-certificates/harbor-ca.crt
   sudo update-ca-certificates
   ```
2. Перезапустите containerd для применения изменений:
   ```bash
   sudo systemctl restart containerd
   ```
3. Проверьте, что сертификат добавлен:
   ```bash
   ls /usr/local/share/ca-certificates/ | grep harbor
   ```

**Симптом:** `Failed to pull image ... project not found`.
**Причина:** Проект `k8s` в Harbor помечен как приватный, но containerd не имеет учётных данных для аутентификации.
**Решение:** Убедитесь, что проект `k8s` в Harbor помечен как **Public**. Если проект приватный, необходимо настроить `containerd_registry_auth` в `group_vars/all/containerd.yml`:
```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: <secure_password>
```

**Симптом:** `manifest unknown` или `name unknown: repository does not exist`.
**Причина:** Образ не был загружен в Harbor или указан неверный путь (тег).
**Решение:** Проверьте наличие образа в Harbor через веб-интерфейс или API:
```bash
# Проверка через crane (если доступен)
crane ls harbor.domain.local/k8s/registry.k8s.io/kube-apiserver

# Проверка через curl
curl -s -k https://harbor.domain.local/v2/k8s/registry.k8s.io/kube-apiserver/tags/list
```

### 2. Проблема Cilium: несовпадение SHA Digest

**Симптом:** Образ есть в Harbor, но Cilium-pod висит в `ImagePullBackOff`.
**Причина:** Kubespray прописывает жесткие digest для образов Cilium в ролях. При миграции через `docker save/load` и последующий push в Harbor оригинальный digest образа может измениться, так как пересоздаются слои и метаданные.
**Решение:** Отключите использование digest в `group_vars/all/offline.yml`:

```yaml
cilium_deploy_with_digest: false
# Также для Hubble и Operator
hubble_ui_deploy_with_digest: false
cilium_operator_deploy_with_digest: false
```

**Валидация:** После применения перезапустите playbook с тегом `cilium`:
```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b --tags "cilium" -v
```

### 3. Проблемы связности: Cluster health unreachable

**Симптом:** Узлы видят друг друга по SSH, но поды не пингуются между узлами.
**Причина:** MTU физического интерфейса не учитывает заголовки инкапсуляции Cilium (VXLAN/Geneve добавляют 50-70 байт). При MTU 1500 на интерфейсе и MTU 1450 в Cilium, пакеты могут фрагментироваться или отбрасываться.

**Диагностика:**
```bash
# Проверка MTU на интерфейсах
ip link show
# → eth0: mtu 1500

# Проверка статуса Cilium
kubectl -n kube-system exec ds/cilium -- cilium status

# Проверка dropped пакетов через Hubble
kubectl -n kube-system exec ds/cilium -- hubble observe --type drop
```

**Решение:** Для виртуальных сред (особенно VMware с MTU 1500) уменьшите MTU Cilium до 1450 в `group_vars/k8s_cluster/k8s-net-cilium.yml`:

```yaml
cilium_mtu: 1450
cilium_tunnel_mode: geneve # Geneve эффективнее VXLAN в vSphere
```

**Валидация:** Проверьте связность между подами на разных узлах:
```bash
# Запустите тестовый под
kubectl run test-net --image=busybox:1.37 --rm -it --restart=Never -- sh
# Внутри пода:
wget -qO- --timeout=5 http://<IP_другого_под>
```

### 4. Ошибки Ansible: "python3-apt not found"

**Симптом:** Плейбук падает на этапе `gathering facts` или установки пакетов с ошибкой `No module named apt_pkg`.
**Причина:** Ansible внутри venv не видит системный модуль `apt`, потому что venv по умолчанию изолирует системные пакеты Python.
**Решение:** Установите `python3-apt` в системе и создайте venv с доступом к системным пакетам:
```bash
# Установка системного модуля (Ubuntu/Debian)
sudo apt install python3-apt -y

# Пересоздание venv с доступом к системным пакетам
rm -rf venv
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Переустановка зависимостей
pip install -r requirements.txt
```

**Валидация:** Проверьте доступность модуля:
```bash
python -c "import apt_pkg; print('apt_pkg OK')"
# → apt_pkg OK
```

### 5. Рассинхронизация времени (NTP)

**Симптом:** Непонятные ошибки `Unauthorized`, `Expired certificate` или `certificate is not valid yet`.
**Причина:** Сертификаты Kubernetes и Harbor привязаны к времени. Если часы на узле отстают/опережают, TLS- Handshake завершается неудачей. Это особенно критично в offline-среде, где нет доступа к внешним NTP-серверам.

**Решение:** Установите и настройте `chrony` на всех узлах, направив их на локальный источник точного времени или internal NTP-сервер:

```bash
# Установка chrony
sudo apt install chrony -y

# Конфигурация (если есть внутренний NTP-сервер)
# /etc/chrony/chrony.conf:
server 192.168.1.1 iburst
# Или если NTP-сервера нет — локальный stratum
# local stratum 10

# Запуск и проверка
sudo systemctl enable --now chrony
chronyc tracking
# → Leap status : Normal
# → System time : 0.000001234 seconds fast of NTP time
```

**Валидация:** Проверьте синхронизацию на всех узлах:
```bash
# На каждом узле
chronyc tracking | grep "System time"
# → System time : 0.000001234 seconds fast of NTP time
```

> Базовая информация по настройке Chrony приведена в **[Chrony — NTP-сервер](../../../../Linux/Networking/Services/chrony_ntp.md)**.

### 6. Недоступность Harbor

**Симптом:** Плейбук падает на этапе загрузки образов с ошибкой `connection refused` или `dial tcp: lookup harbor.domain.local: no such host`.
**Причина:** Сервис Harbor недоступен из-за остановки контейнера, проблем с DNS-разрешением или блокировки порта.

**Диагностика:**
```bash
# Проверка DNS-разрешения
nslookup harbor.domain.local
# → Address: 192.168.1.100

# Проверка доступности порта
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}

# Проверка статуса Harbor (на узле Harbor)
sudo docker ps | grep harbor
```

**Решение:**
```bash
# Если Harbor остановлен — перезапуск
cd /opt/harbor
sudo ./install.sh --with-trivy

# Если DNS не работает — добавьте запись в /etc/hosts на всех узлах
echo "192.168.1.100 harbor.domain.local" | sudo tee -a /etc/hosts
```

### 7. DiskPressure: kubelet не может запускать поды

**Симптом:** Узел переходит в статус `NotReady`. В логахkubelet: `The node was low on resource: ephemeral-storage`.
**Причина:** Исчерпано дисковое пространство на узле. В offline-среде это происходит чаще, так как образы не очищаются автоматически, а ручное управление требует осознанности.

**Диагностика:**
```bash
# Проверка свободного места
df -h
# → /dev/sda1  50G   48G  2.0G  96% /

# Проверка статуса узла
kubectl describe node <node-name> | grep -A 5 Conditions

# Проверка размера образов
crictl images
```

**Решение:**
```bash
# Очистка неиспользуемых образов
crictl rmi --prune

# Очистка файлов логов Kubernetes
sudo journalctl --vacuum-time=72h

# Проверка больших файлов
du -sh /var/lib/containerd/* | sort -rh | head -10
```

**Профилактика:** Настройте автоматическую очистку:
```bash
# Добавление cron-задачи для очистки образов
echo "0 3 * * * root crictl rmi --prune 2>/dev/null" | sudo tee /etc/cron.d/cleanup-images
```

### 8. Kubelet не запускается после установки

**Симптом:** Узел в статусе `NotReady` после завершения playbook. `systemctl status kubelet` показывает `inactive (dead)` или反复 `restart`.
**Причина:** Неверный kubeconfig, отсутствие сертификатов, или проблемы с containerd.

**Диагностика:**
```bash
# Проверка статуса kubelet
sudo systemctl status kubelet

# Просмотр логов
sudo journalctl -u kubelet -f --no-pager | tail -50

# Проверка наличия kubeconfig
ls -la /etc/kubernetes/kubelet.conf
```

**Типичные ошибки и решения:**
| Сообщение об ошибке | Причина | Решение |
| :--- | :--- | :--- |
| `unable to load kubeconfig` | Файл отсутствует или невалиден | Проверьте `/etc/kubernetes/kubelet.conf` и права доступа |
| `failed to connect to containerd` | Containerd не запущен | `sudo systemctl restart containerd` |
| `certificate has expired` | Истекли сертификатыkubelet | `sudo kubeadm certs renew kubelet` |
| `error: unable to recognize` | Невалидный kubeconfig | Перескопируйте `/etc/kubernetes/admin.conf` |

### 9. etcd: проблемы с кворумом и здоровьем

**Симптом:** API-сервер не отвечает, поды в `Pending`, kubectl выдает `The connection to the server was refused`.
**Причина:** etcd потерял кворум из-за сетевых проблем, нехватки места на диске или рассинхронизации времени.

**Диагностика:**
```bash
# Проверка здоровья etcd через API
ETCDCTL_API=3 etcdctl endpoint health --cluster \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Просмотр статуса кворума
ETCDCTL_API=3 etcdctl member list --cluster \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
```

**Решение:**
```bash
# Проверка дискового пространства etcd
df -h /var/lib/etcd

# Проверка задержек диска (etcd требует <10ms)
sudo iostat -x 1 5

# Если etcd запущен как контейнер в Kubespray
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl endpoint health --cluster
```

> Подробная информация по troubleshooting etcd приведена в разделе **[etcd: Устранение неполадок](../../../../etcd/troubleshooting.md)**.

### 10. CoreDNS: отказ разрешения имён

**Симптом:** Поды не могут разрешить DNS-имена (`nslookup kubernetes.default` возвращает `SERVFAIL`). Приложения ссылаются на сервисы по именам, которые не резолвятся.
**Причина:** CoreDNS не запущен, конфигурация DNS-сервера неверна, или NetworkPolicy блокирует DNS-трафик (UDP/TCP 53).

**Диагностика:**
```bash
# Статус подов CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns

# Логи CoreDNS
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50

# Проверка конфигурации CoreDNS
kubectl -n kube-system get configmap coredns -o yaml

# Тест DNS из пода
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
```

**Решение:**
```bash
# Перезапуск CoreDNS
kubectl -n kube-system rollout restart deployment coredns

# Проверка Service ClusterIP для CoreDNS
kubectl -n kube-system get svc kube-dns
# → NAME       TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)
# → kube-dns   ClusterIP   10.233.0.3   <none>        53/UDP,53/TCP
```

### 11. Helm: ошибки установки Cilium через OCI

**Симптом:** Playbook падает на этапе установки Cilium с ошибкой `failed: timed out` или `oci:// registry pull error`.
**Причина:** Helm не может скачать чарт из OCI-репозитория Harbor из-за проблем с авторизацией, неверного URL или отсутствия чарта.

**Диагностика:**
```bash
# Проверка доступности чарта в Harbor
helm search oci://harbor.domain.local/helm/cilium --version 1.19.6

# Ручная попытка установки для отладки
helm install cilium oci://harbor.domain.local/helm/cilium \
  --version 1.19.6 \
  --namespace kube-system

# Проверка логов Helm-контроллера
kubectl -n kube-system logs -l app.kubernetes.io/name=helm-controller --tail=50
```

**Решение:**
```bash
# Публикация чарта в Harbor (если отсутствует)
helm registry login harbor.domain.local
helm push /opt/kubespray-releases/cilium-1.19.6.tgz oci://harbor.domain.local/helm

# Проверка переменных Kubespray
grep -E "cilium_install|cilium_version" group_vars/all/offline.yml
```

### 12. Ansible: таймауты SSH и проблемы подключения

**Симптом:** Playbook зависает на этапе `Gathering Facts` или завершается с `UNREACHABLE!`.
**Причина:** Проблемы с SSH-подключением к целевым узлам: неверные ключи, заблокированный порт 22, или узлы не отвечают.

**Диагностика:**
```bash
# Проверка SSH-подключения
ssh -o ConnectTimeout=5 admin@192.168.1.104

# Проверка инвентаря
ansible -i inventory/offline_cluster/inventory.ini all -m ping

# Запуск playbook с увеличенным таймаутом
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin \
  --timeout 60 \
  -e "ansible_ssh_retries=3"
```

**Решение:**
```bash
# Проверка SSH-ключей
ssh-add -l

# Проверка прав на SSH-ключ
chmod 600 ~/.ssh/id_rsa

# Если используется ProxyJump
ssh -J admin@pc-inet admin@192.168.1.104
```

---

## Дополнительная информация

### Команды быстрой диагностики на узле

**Проверка работы containerd:**
```bash
sudo crictl ps        # Список запущенных контейнеров
sudo crictl images    # Список загруженных образов
sudo crictl info | jq .config  # Конфигурация рантайма
```

**Проверка логов системных сервисов:**
```bash
sudo journalctl -u kubelet -f --no-pager
sudo journalctl -u containerd -f --no-pager
```

**Анализ сетевых сбросов (Drop) через Cilium:**
```bash
kubectl -n kube-system exec ds/cilium -- hubble observe --type drop
```

**Проверка дискового пространства:**
```bash
df -h / /var/lib/containerd /var/lib/etcd
```

**Проверка сертификатов:**
```bash
# Проверка срока действия сертификата apiserver
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -dates

# Проверка сертификата Harbor
openssl s_client -connect harbor.domain.local:443 </dev/null 2>/dev/null | openssl x509 -noout -dates
```

**Проверка DNS:**
```bash
# Резолвинг имени Harbor
nslookup harbor.domain.local
# Или через systemd-resolve
resolvectl query harbor.domain.local
```

### Быстрая шпаргалка: симптомы и первые действия

| Симптом | Первое действие |
| :--- | :--- |
| `ImagePullBackOff` | `crictl pull <образ>` на проблемном узле; проверить `/etc/containerd/certs.d/` |
| `x509: certificate signed by unknown authority` | Добавить CA Harbor в `/usr/local/share/ca-certificates/` |
| Узел `NotReady` | `systemctl status kubelet && journalctl -u kubelet -f` |
| `etcd cluster unhealthy` | `etcdctl endpoint health --cluster`; проверить место на диске |
| DNS не работает | `kubectl -n kube-system get pods -l k8s-app=kube-dns` |
| Playbook `UNREACHABLE` | `ssh admin@<узел>`; проверить SSH-ключи |
| Harbor недоступен | `curl -sk https://harbor.domain.local/api/v2.0/health` |
| Cilium `ImagePullBackOff` | `cilium_deploy_with_digest: false` в offline.yml |
| Время рассинхронизировано | `chronyc tracking` на всех узлах |

### Чек-лист перед запуском playbook

Перед запуском `cluster.yml` в offline-режиме убедитесь:

- [ ] Harbor запущен и доступен со всех узлов (`curl -k https://harbor.domain.local`).
- [ ] Проект `k8s` в Harbor помечен как **Public** (или настроена авторизация в `containerd_registry_auth`).
- [ ] CA-сертификат Harbor добавлен на все узлы в `/usr/local/share/ca-certificates/`.
- [ ] NTP-сервис (`chrony`) работает на всех узлах (`chronyc tracking`).
- [ ] На всех узлах установлен `python3-apt` (для Ubuntu/Debian).
- [ ] venv создан с флагом `--system-site-packages`.
- [ ] В `offline.yml` указаны корректные пути к кэшу и релизам.
- [ ] SSH-доступ настроен и работает со всех узлов.
- [ ] Достаточно места на диске (минимум 10 ГБ на узле).
- [ ] Инвентарь содержит IP-адреса закрытого контура (не pc-inet).

### См. также

- **[Проверка кластера](./cluster_verification.md)** — регламент валидации систем.
- **[План offline-установки](./offline_practical.md)** — дорожная карта проекта.
- **[Общая диагностика Air-gapped](../../../../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** — ошибки загрузки образов в изолированных средах.
