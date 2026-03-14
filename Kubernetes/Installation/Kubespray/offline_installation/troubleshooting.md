# Kubespray: Offline установка — Troubleshooting

## Проблемы с авторизацией containerd

### Проблема: Ошибка containerd авторизации

**Симптом:**

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/cilium:v1.18.5"
```

**Решение:**

Проект `k8s` в Harbor должен быть **публичным**. Containerd не считывает логин/пароль из файла конфигурации автоматически.

**Проверка:**

```bash
# В веб-интерфейсе Harbor проверить проект k8s
# Projects → k8s → Public → должен быть включен
```

---

## Проблемы с Cilium

### Проблема: Cilium image с SHA digest

**Симптом:**

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/cilium:v1.18.5@sha256:..."
rpc error: code = NotFound desc = failed to pull and unpack image
```

**Причина:** При загрузке в Harbor SHA образов изменяется.

**Решение:**

Отключить проверку digest в файле `group_vars/k8s_cluster/k8s-net-cilium.yml`:

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

### Проблема: Cilium-operator image не найден

**Симптом:**

```
Failed to pull image "harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5"
```

**Причина:** Образ не загружается автоматически через Kubespray.

**Решение:**

Скачать и запушить вручную:

```bash
# На машине с интернетом
docker pull quay.io/cilium/operator-generic:v1.18.5
docker tag quay.io/cilium/operator-generic:v1.18.5 \
  harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5
docker push harbor.domain.local/k8s/quay.io/cilium/operator-generic:v1.18.5

# В закрытом контуре перезапустить pod
kubectl delete po -n kube-system -l name=cilium-operator
```

### Проблема: Permission denied для cilium-mount

**Симптом:**

```
cp: cannot create regular file '/hostbin/cilium-mount': Permission denied
```

**Решение:**

В файле `group_vars/k8s_cluster/k8s-cluster.yml`:

```yaml
# This is the user that owns the cluster installation.
# Note: cilium needs to set kube_owner to root
kube_owner: root
```

### Проблема: Cilium не поднимается на VMware

**Симптом:**

```
Cluster health: 1/5 reachable
```

**Причина:** VMware плохо дружит с Cilium на дефолтном порту.

**Решение:** Изменить tunnel mode на geneve:

```yaml
# group_vars/k8s_cluster/k8s-net-cilium.yml
cilium_tunnel_mode: geneve
cilium_mtu: "1450"
# tunnelPort: 8223  # Это не сработало для vxlan
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

### Проблема: ImagePullPolicy требует обновления

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

## Проблемы с Hubble

### Проблема: Hubble-relay не резолвит DNS

**Симптом:**

```
A record lookup error: lookup hubble-peer.kube-system.svc.k8s.domain.local
on 169.254.25.10:53: read udp 10.233.67.64:56328->169.254.25.10:53: i/o timeout
```

**Решение:**

Добавить в `k8s-net-cilium.yml`:

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

## Общие проблемы

### Проблема: Pod в статусе ImagePullBackOff

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

### Проблема: Ansible playbook завершается ошибкой

**Диагностика:**

```bash
# Запуск с подробным логом
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin -vvv

# Запуск только для конкретного хоста
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin --limit master-1-k8s
```

### Проблема: Ноды не в статусе Ready

**Проверка:**

```bash
kubectl get nodes
kubectl describe node <node-name>

# Проверка kubelet
systemctl status kubelet
journalctl -u kubelet -f
```

---

## Связанные документы

- **[Определения](./offline_definitions.md)** — базовые термины
- **[Основные концепции](./offline_concepts.md)** — принципы offline-установки
- **[Практические сценарии](./offline_practical.md)** — пошаговая инструкция
- **[Post-Install: Управление кластером](./post_install_management.md)** — управление после установки
- **[Проверка кластера](./cluster_verification.md)** — валидация установки

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
