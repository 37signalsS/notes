# Практические сценарии DPDK и SR-IOV

## Сценарий 1: Kubernetes + SR-IOV

```yaml
# SR-IOV Network Device Plugin
apiVersion: v1
kind: Pod
metadata:
  name: sriov-pod
  annotations:
    k8s.v1.cni.cncf.io/networks: sriov-network
spec:
  containers:
  - name: app
    image: my-app:latest
    resources:
      limits:
        intel.com/sriov_net: '1'  # Запрос 1 VF
```

## Сценарий 2: OVS-DPDK

```bash
# Установка OVS с DPDK
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024"

# Создание DPDK порта
ovs-vsctl add-port br0 dpdk0 -- set Interface dpdk0 type=dpdk \
    options:dpdk-devargs=0000:04:00.0

# Проверка
ovs-vsctl show
```

## Сценарий 3: VPP (Vector Packet Processing)

```bash
# Конфигурация VPP
# /etc/vpp/startup.conf
dpdk {
  dev 0000:04:00.0
  num-mbufs 131072
}

# Запуск
systemctl start vpp

# CLI VPP
vppctl show interfaces
vppctl show hardware
```

## Дополнительная информация

- [DPDK Official Documentation](https://doc.dpdk.org/guides/)
- [SR-IOV Specification](https://pcisig.com/specifications/iov/)
- [Intel DPDK Getting Started](https://www.intel.com/content/www/us/en/developer/topic-technology/open/dpdk.html)
- [OVS-DPDK Documentation](https://docs.openvswitch.org/en/latest/intro/install/dpdk/)
- [VPP Documentation](https://fd.io/docs/vpp/)
