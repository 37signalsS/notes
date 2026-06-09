# Kubespray: Offline установка — Проверка кластера

## Определения

**Валидация кластера (Cluster Verification)** — комплекс мероприятий по проверке работоспособности всех системных компонентов после завершения установки в изолированной среде.

**Сквозная проверка (E2E Check)** — тестирование цепочки «Registry → Runtime → Pod → Network → Ingress» для подтверждения отсутствия блокировок в закрытом контуре.

Базовые определения компонентов (Control Plane, CNI, MetalLB) приведены в **[определениях offline-установки](./offline_definitions.md)**.

---

## Основные концепции

### Критерии успешной установки в offline-режиме

В отличие от стандартной установки, в закрытом контуре критически важно убедиться в корректности путей загрузки образов и отсутствии попыток обращения к внешним DNS/реестрам.

**Ключевые показатели:**

- **Узлы (Nodes):** все участники кластера находятся в статусе `Ready`.
- **Реестр (Registry):** все системные образы загружены из локального Harbor (проверяется через `crictl images`).
- **Сеть (Network):** Cilium показывает полную связность (`Cluster health: N/N reachable`).
- **Сервисы (Services):** MetalLB успешно назначает внешние IP (External IP) из локального пула.
- **Инструментарий (Tools):** Hubble UI доступен и визуализирует трафик.

---

## Практические сценарии

### 1. Проверка состояния узлов и системных подов

Первичная диагностика через стандартные средства Kubernetes.

**Статус узлов:**

```bash
kubectl get nodes -o wide
# → Ожидаемый результат: все узлы в статусе Ready, версия ядра и runtime соответствуют заданным
```

**Статус системных компонентов:**

```bash
kubectl get pods -n kube-system
# → Ожидаемый результат: все поды в статусе Running
```

*Если поды находятся в статусе `ImagePullBackOff` — проверьте доступность Harbor и настройки в `group_vars/all/offline.yml`.*

### 2. Валидация сетевого плагина Cilium

Проверка eBPF-связности и статуса Hubble.

**Общий статус Cilium:**

```bash
kubectl -n kube-system exec -it ds/cilium -- cilium status
# → Ожидаемый результат: KubeProxyReplacement: True, Cluster health: reachable
```

**Проверка Hubble Relay:**

```bash
kubectl -n kube-system exec -it ds/cilium -- hubble status
# → Ожидаемый результат: Healthcheck (OK)
```

### 3. Тестирование балансировщика и Ingress

Проверка цепочки внешнего доступа.

**Проверка пула MetalLB:**

```bash
kubectl get ipaddresspool -n metallb-system
kubectl get l2advertisement -n metallb-system
# → Ожидаемый результат: отображение настроенных диапазонов IP
```

**Проверка внешнего IP для Hubble UI:**

```bash
kubectl get svc -n kube-system hubble-ui
# → Ожидаемый результат: в колонке EXTERNAL-IP отображается адрес из локального пула
```

### 4. Проверка DNS внутри кластера

Валидация разрешения имен без выхода за пределы контура.

```bash
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
# → Ожидаемый результат: Server: 10.233.0.3, Address 1: 10.233.0.3 kube-dns.kube-system.svc.cluster.local
```

### 5. Диагностика Runtime (containerd) на узлах

Проверка того, что образы действительно берутся из локального реестра.

```bash
# Выполняется на любом узле кластера
sudo crictl images | grep "harbor.domain.local"
# → Ожидаемый результат: список образов с префиксом локального Harbor
```

---

## Дополнительная информация

### Чек-лист финальной приемки

- [ ] Все узлы в статусе `Ready`.
- [ ] Отсутствуют ошибки `ImagePullBackOff` во всех пространствах имен.
- [ ] MetalLB успешно назначил IP сервису Hubble UI.
- [ ] Hubble UI открывается в браузере и отображает карту сети.
- [ ] Тестовые поды успешно резолвят `kubernetes.default.svc.cluster.local`.

### Связанные темы

- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — процедура запуска установки.
- **[Шаг 5: Настройка MetalLB и Ingress](./step5_metallb_ingress.md)** — конфигурация внешнего доступа.
- **[Troubleshooting](./troubleshooting.md)** — решение проблем при неудачных проверках.
- **[Базовые концепции Kubespray](../kubespray_install/basic_concepts.md)** — общие методы управления.
