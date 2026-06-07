# Kubespray: Offline установка — Troubleshooting

## Определения

**Troubleshooting** — процесс диагностики и устранения проблем, возникающих при развёртывании и эксплуатации offline-кластера Kubernetes.

**ImagePullBackOff** — статус pod'а, указывающий на невозможность загрузки контейнерного образа (подробнее в [Определениях](../../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)).

**SHA Digest** — хэш-идентификатор образа контейнера, который может изменяться при загрузке в локальный реестр Harbor.

---

## Основные концепции

### Категории проблем offline-установки

| Категория | Типичные симптомы | SSoT для решения |
| :--- | :--- | :--- |
| **Авторизация containerd** | `Failed to pull image` | Ниже |
| **Cilium image** | `SHA digest not found` | Ниже |
| **Сетевые проблемы** | `Cluster health: N/5 reachable` | Ниже |
| **Hubble DNS** | `i/o timeout` при резолве | Ниже |
| **Ansible ошибки** | Playbook завершается ошибкой | Ниже |
| **Node NotReady** | Узлы не в статусе `Ready` | [cluster_verification.md](./cluster_verification.md) |

### Общий подход к диагностике

1. **Идентификация симптома** — определить точную ошибку из логов
2. **Локализация компонента** — определить затронутый компонент (Cilium, Harbor, Ansible)
3. **Применение решения** — выполнить шаги из соответствующего раздела
4. **Верификация** — проверить устранение проблемы

---

## Практические сценарии

### Проблемы с авторизацией containerd

#### Симптом

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/cilium:v1.18.5"
```

#### Причина

Проект `k8s` в Harbor не является публичным. Containerd не считывает логин/пароль из файла конфигурации автоматически.

#### Решение

Проверить в веб-интерфейсе Harbor:

```
Projects → k8s → Public → должен быть включен
```

---

### Проблемы с Cilium

#### Cilium image с SHA digest

**Симптом:**

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/cilium:v1.18.5@sha256:..."
rpc error: code = NotFound desc = failed to pull and unpack image
```

**Причина:** При загрузке в Harbor SHA образов изменяется.

**Решение:** Отключить проверку digest в файле `group_vars/k8s_cluster/k8s-net-cilium.yml`:

```yaml
cilium_extra_values:
  image:
    useDigest: false
    digest: ""
  operator:
    image:
      useDigest: false
      digest: ""
  envoy:
    image:
      useDigest: false
      digest: ""
  hubble:
    relay:
      image:
        useDigest: false
        digest: ""
    ui:
      backend:
        image:
          useDigest: false
          digest: ""
      frontend:
        image:
          useDigest: false
          digest: ""
```

**Применение изменений:**

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "cilium,network" -v
```

#### Cilium-operator image не найден

**Симптом:**

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5"
```

**Причина:** Образ не загружается автоматически через Kubespray.

**Решение:** Скачать и запушить вручную:

```bash
# На машине с интернетом
docker pull quay.io/cilium/operator-generic:v1.18.5
docker tag quay.io/cilium/operator-generic:v1.18.5 \
  harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5
docker push harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5

# В закрытом контуре перезапустить pod
kubectl delete po -n kube-system -l name=cilium-operator
```

#### Permission denied для cilium-mount

**Симптом:**

```
cp: cannot create regular file '/hostbin/cilium-mount': Permission denied
```

**Решение:** В файле `group_vars/k8s_cluster/k8s-cluster.yml`:

```yaml
# This is the user that owns the cluster installation.
# Note: cilium needs to set kube_owner to root
kube_owner: root
```

#### Cilium не поднимается на VMware

**Симптом:**

```
Cluster health: 1/5 reachable
```

**Причина:** VMware плохо дружит с Cilium на дефолтном порту.

**Решение:** Изменить tunnel mode на geneve в файле `group_vars/k8s_cluster/k8s-net-cilium.yml`:

```yaml
cilium_tunnel_mode: geneve
cilium_mtu: "1450"
```

**Перезапуск:**

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "cilium,network" -v

kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout status ds/cilium
```

**Проверка:**

```bash
kubectl -n kube-system exec -it ds/cilium -- cilium status | \
  egrep -i 'KubeProxyReplacement|Cluster health'
```

**Ожидаемый вывод:**

```
KubeProxyReplacement:    True   [ens33  192.168.1.104 (Direct Routing)]
Cluster health:          5/5 reachable
```

#### ImagePullPolicy требует обновления

**Симптом:** Pod не подтягивает обновленный образ.

**Решение:**

```bash
# Проверить текущую политику
kubectl -n kube-system get deploy cilium-operator \
  -o jsonpath='{.spec.template.spec.containers[0].imagePullPolicy}{"\n"}'

# Временно изменить на Always
kubectl -n kube-system patch deploy cilium-operator --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Always"}]'

# Пересоздать pod
kubectl delete po -n kube-system -l name=cilium-operator

# Вернуть обратно на IfNotPresent
kubectl -n kube-system patch deploy cilium-operator --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"IfNotPresent"}]'
```

---

### Проблемы с Hubble

#### Hubble-relay не резолвит DNS

**Симптом:**

```
A record lookup error: lookup hubble-peer.kube-system.svc.k8s.domain.local
on 169.254.25.10:53: read udp 10.233.67.64:56328->169.254.25.10:53: i/o timeout
```

**Решение:** Добавить в файл `k8s-net-cilium.yml`:

```yaml
cilium_kube_proxy_replacement: true
```

**Перезапуск с тегами:**

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "cilium,network,kubernetes-apps" -v

kubectl delete po -l k8s-app=hubble-relay -n kube-system
```

---

### Общие проблемы

#### Pod в статусе ImagePullBackOff

**Диагностика:**

```bash
kubectl describe pod <pod-name> -n kube-system
kubectl logs <pod-name> -n kube-system
```

**Возможные причины:**

1. Образ не загружен в Harbor
2. Неправильный тег образа
3. Проблемы с авторизацией
4. Проект Harbor не публичный

#### Ansible playbook завершается ошибкой

**Диагностика:**

```bash
# Запуск с подробным логом
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin -vvv

# Запуск только для конкретного хоста
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin --limit master-1-k8s
```

#### Ноды не в статусе Ready

Полная диагностика описана в [cluster_verification.md](./cluster_verification.md#Диагностика-проблем).

**Краткая проверка:**

```bash
kubectl get nodes
kubectl describe node <node-name>

# Проверка kubelet
systemctl status kubelet
journalctl -u kubelet -f
```

---

## Дополнительная информация

### Связанные темы

Базовые термины описаны в [определениях offline-установки](./offline_definitions.md), принципы — в [основных концепциях](./offline_concepts.md). Полная проверка кластера — в [cluster_verification.md](./cluster_verification.md), управление после установки — в [post_install_management.md](./post_install_management.md). Обзор этапов — в [offline_practical.md](./offline_practical.md).
