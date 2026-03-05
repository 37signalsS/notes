# Node Unavailability: Проблемы с сетью

## 3. Проблемы с сетью (Network Unavailable)

**Симптомы:**

- Condition `NetworkUnavailable=True`
- Поды не получают IP-адреса
- CNI плагин не работает

**Диагностика:**

```bash
# Проверка CNI подов
kubectl get pods -n kube-system -l k8s-app=<cni-plugin>

# Логи CNI
kubectl logs -n kube-system -l k8s-app=<cni-plugin>

# Проверка CNI конфигурации
ls -la /etc/cni/net.d/
```

**Решение:**

```bash
# Перезапуск CNI плагина
kubectl rollout restart daemonset -n kube-system <cni-ds-name>

# Проверка правил iptables
iptables -L -n | grep -E 'KUBE|CNI'

# Пересоздание CNI конфигурации
kubectl apply -f <cni-manifest.yaml>
```

> **См. также:** [`../../../Security/network_policies.md`](../../../Security/network_policies.md), [`../../../Security/network_policies/calico.md`](../../../Security/network_policies/calico.md)

## 4. Узел выключен или недоступен по сети

**Симптомы:**

- Статус узла: `Unknown`
- Нет связи по SSH
- Сервер не отвечает на ping

**Причины:**

- Аппаратный сбой
- Проблемы с питанием
- Сетевая изоляция

**Решение:**

```bash
# Проверка физического сервера (IPMI/iLO)
ipmitool power status

# Принудительное удаление узла (если не вернется)
kubectl delete node <node-name>

# Для StatefulSet подов — пересоздание на другом узле
kubectl delete pod <pod-name> --force --grace-period=0
```

> **Важно:** При удалении узла поды будут пересозданы на других узлах (если есть контроллер).
