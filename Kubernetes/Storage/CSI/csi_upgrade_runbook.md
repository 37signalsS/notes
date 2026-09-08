# Runbook: Обновление CSI-драйверов в продакшене

## Определения

**CSI Driver Upgrade** — процесс обновления CSI-драйвера (controller и node plugin) в работающем Kubernetes-кластере без остановки приложений. Требует поэтапного подхода из-за зависимости томов от драйвера: некорректное обновление может привести к зависанию PVC, потере доступа к данным или ошибкам монтирования.

Ключевые компоненты при обновлении:
- **CSI Driver** (код драйвера)
- **Sidecar-контейнеры** (external-provisioner, external-attacher, external-resizer, livenessprobe)
- **Helm-чарт** или манифесты
- **CRD** (VolumeSnapshotClass, CSIDriver)

---

## Теоретический блок

### Матрица совместимости

Перед обновлением проверяйте совместимость версий:

| Компонент | Минимальная версия для K8s 1.27+ | Примечания |
| :--- | :--- | :--- |
| CSI Driver | Зависит от вендора | Проверить RELEASES.md |
| external-provisioner | v3.5+ | 3.x для K8s 1.25+ |
| external-attacher | v4.4+ | 4.x для K8s 1.25+ |
| external-resizer | v1.9+ | 1.x стабильный |
| external-snapshotter | v6.2+ | 6.x для K8s 1.25+ |
| node-driver-registrar | v2.9+ | 2.x стабильный |
| livenessprobe | v2.11+ | 2.x стабильный |

### Порядок обновления

```
1. Controller Plugin (Deployment)
   └─ Обновить controller ДО node plugin
   └─ Controller обратно совместим со старыми node plugin

2. Node Plugin (DaemonSet)
   └─ Обновить после controller
   └─ Поэтапно: 1 узел → проверка → остальные
   └─ Drain узла перед обновлением node plugin

3. CRD (VolumeSnapshotClass, CSIDriver)
   └─ Обновить ДО или ПОСЛЕ кода (обычно совместимо)
```

### Risks и Mitigation

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| Controller падает во время обновления | Новые тома не создаются, attach/detach не работает | Leader election, HA controller (2+ реплики) |
| Node plugin несовместим с новым controller | Тома не монтируются на новых узлах | Обновлять controller первым, проверять совместимость |
| Sidecar обновлён до несовместимой версии | Ошибки в логах, PVC зависают | Использовать проверенные матрицей версии |
| DaemonSet обновился на всех узлах одновременно | Все node plugin перезапущены → I/O errors | `maxUnavailable: 1` в DaemonSet, поэтапное обновление |

---

## Практический блок

### Pre-upgrade чеклист

- [ ] **Бэкап**: Velero backup создан и проверен
- [ ] **Матрица совместимости**: версии sidecar совместимы с K8s и драйвером
- [ ] **Тестовый кластер**: обновление проверено на staging/dev
- [ ] **Окно простоя**: согласовано (если требуется)
- [ ] **Rollback план**: старый Helm-чарт сохранён
- [ ] **Мониторинг**: алерты на PVC и CSI-операции настроены
- [ ] **Контрольные тома**: тестовые PVC созданы и проверены

### Шаг 1: Backup

```bash
# Создание backup перед обновлением
velero backup create pre-csi-upgrade-backup \
  --include-namespaces kube-system \
  --wait

# Проверка
velero backup describe pre-csi-upgrade-backup
```

### Шаг 2: Обновление Controller Plugin

```bash
# Вариант A: Helm upgrade
helm upgrade ceph-csi-rbd ceph-csi/ceph-csi-rbd \
  --namespace rook-ceph \
  --set csiPluginTolerations[0].key=CriticalAddonsOnly \
  --set csiPluginTolerations[0].operator=Exists \
  --wait --timeout 5m

# Вариант B: kubectl apply манифестов
kubectl apply -f csi-rbdplugin-provisioner-new.yaml -n rook-ceph

# Проверка controller
kubectl get pods -n rook-ceph -l app=csi-rbdplugin-provisioner -o wide
# → Ожидаемый результат: все поды в Running, READY 6/6
kubectl logs -n rook-ceph -l app=csi-rbdplugin-provisioner -c csi-provisioner --tail=50
# → Ожидаемый результат: нет ошибок, provisioner работает
```

### Шаг 3: Проверка controller после обновления

```bash
# Проверка CSIDriver объекта
kubectl get csidriver rbd.csi.ceph.com -o yaml | grep -A5 version

# Проверка создания тестового PVC
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-upgrade-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ceph-rbd
  resources:
    requests:
      storage: 1Gi
EOF

kubectl get pvc test-upgrade-pvc
# → Ожидаемый результат: Bound за <30 секунд

kubectl delete pvc test-upgrade-pvc
```

### Шаг 4: Обновление Node Plugin (поэтапно)

```bash
# Обновление DaemonSet (node plugin обновится по одному узлу)
kubectl rollout status daemonset/csi-rbdplugin -n rook-ceph

# Если DaemonSet не обновляется автоматически:
kubectl rollout restart daemonset/csi-rbdplugin -n rook-ceph

# Мониторинг обновления (ожидаем пока каждый узел обновится)
kubectl get pods -n rook-ceph -l app=csi-rbdplugin -o wide -w
# → Каждый под обновляется последовательно
# → При ошибке на одном узле — остальные продолжают работать
```

### Шаг 5: Проверка после обновления

```bash
# 1. Все поды драйвера в Running
kubectl get pods -n rook-ceph -l app=csi-rbdplugin-provisioner
kubectl get pods -n rook-ceph -l app=csi-rbdplugin

# 2. Драйвер зарегистрирован на всех узлах
kubectl get csinodes -o yaml | grep -A3 rbd.csi.ceph.com

# 3. Существующие тома работают
kubectl get pvc -A | grep Bound
kubectl exec <pod-with-nfs-or-rbd> -- df -h /data

# 4. Новые тома создаются
kubectl apply -f test-pvc.yaml && kubectl get pvc test-pvc
kubectl delete pvc test-pvc

# 5. Снапшоты работают (если используются)
kubectl apply -f test-snapshot.yaml && kubectl get volumesnapshot test-snap
kubectl delete volumesnapshot test-snap

# 6. Расширение томов работает
kubectl patch pvc test-pvc -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'

# 7. Метрики доступны
kubectl port-forward -n monitoring svc/prometheus 9090
# → В Prometheus: csi_operations_seconds
```

### Шаг 6: Rollback (если что-то пошло не так)

```bash
# Откат controller
helm rollback ceph-csi-rbd <REVISION> --namespace rook-ceph

# Или откат через kubectl
kubectl apply -f csi-rbdplugin-provisioner-old.yaml -n rook-ceph

# Откат node plugin
kubectl rollout undo daemonset/csi-rbdplugin -n rook-ceph

# Проверка отката
kubectl get pods -n rook-ceph -l app=csi-rbdplugin-provisioner
kubectl get pods -n rook-ceph -l app=csi-rbdplugin
```

### Диагностика при проблемах

```bash
# Проблема: PVC завис в Pending после обновления
kubectl describe pvc <name>
# → Ищите события: FailedProvisioning, ProvisioningFailed

# Проблема: существующий под не может примонтировать том
kubectl describe pod <name> | grep -A10 Events
# → Ищите: MountVolume.SetUp failed, VolumeAttachError

# Проблема: node plugin не зарегистрирован
kubectl get csinodes <node> -o yaml | grep -A5 rbd.csi.ceph.com
# → Если пусто: проверить DaemonSet и логи node plugin

# Проблема: leader election loop
kubectl logs -n rook-ceph -l app=csi-rbdplugin-provisioner -c csi-provisioner | grep -i leader
# → Если loop: проверить RBAC для leader election

# Проблема: sidecar не может подключиться к драйверу
kubectl logs -n rook-ceph -l app=csi-rbdplugin-provisioner -c csi-provisioner | grep -i "connection refused"
# → Проверить сокет драйвера: ls /var/lib/kubelet/plugins/rbd.csi.ceph.com/csi.sock
```

---

## Дополнительная информация

### Связанные темы
- [CSI — Обзор](./csi_overview.md) — архитектура и компоненты
- [CSI — Сравнение драйверов](./csi_drivers_comparison.md) — установка и настройка
- [Velero — Обзор](../../../ToolsUtilities/velero-overview.md) — бэкап перед обновлением
- [Обновление кластеров](../../Operations/upgrading_clusters.md) — обновление K8s

### Официальные источники
- [CSI Sidecar Versions](https://kubernetes-csi.github.io/docs/sidecar-containers.html) — версии sidecar
- [CSI Driver Release Notes](https://github.com/ceph/ceph-csi/blob/devel/docs/drivers.md) — Ceph CSI
- [Helm Rollback](https://helm.sh/docs/helm/helm_rollback/) — откат Helm-релизов
