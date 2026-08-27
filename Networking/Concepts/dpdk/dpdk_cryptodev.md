# Cryptodev / IPsec в DPDK

### Определения

- **librte_cryptodev**: Библиотека DPDK для управления аппаратным и программным шифрованием (crypto acceleration). Поддерживает hardware crypto (Intel QAT, virtio-crypto) и software crypto (OpenSSL, IPSec_mb).
- **Inline crypto**: Шифрование/дешифрование выполняется непосредственно в NIC (Intel E810 Inline IPsec). Пакеты не покидают NIC до завершения криптооперации → минимальная latency.
- **Lookaside crypto**: Шифрование/дешифрование выполняется в отдельном crypto device (Intel QAT, AMD CCP). Пакеты передаются из NIC в crypto device через DMA → средняя latency.
- **Intel QAT (QuickAssist Technology)**: Аппаратный крипто-акселератор Intel. Поддерживает AES, SHA, RSA, ECC, Huffman compression. Доступен как PCIe device.
- **IPsec (Internet Protocol Security)**: Протокол сетевого уровня для шифрования и аутентификации IP-пакетов. Режимы: Transport (端到端), Tunnel (шлюз-шлюз). Алгоритмы: AES-GCM, AES-CBC+HMAC-SHA256.
- **ESP (Encapsulating Security Payload)**: Протокол IPsec, обеспечивающий конфиденциальность и аутентификацию. Заголовок ESP добавляется между IP-заголовком и данными.
- **IKE (Internet Key Exchange)**: Протокол для установления Security Associations (SA) в IPsec. Два раунда: Main Mode (аутентификация) + Quick Mode (установка ключей).
- **SA (Security Association)**: Набор параметров шифрования (алгоритм, ключ, SPI, sequence number) для одного направления IPsec-туннеля.
- **AES-GCM (Advanced Encryption Standard - Galois/Counter Mode)**: Симметричный алгоритм шифрования + аутентификации. Самый быстрый и безопасный режим для IPsec. Hardware offload на Intel E810 и QAT.
- **Crypto session**: Конфигурация крипто-операции (алгоритм, ключ, IV) для конкретного flow. Создаётся один раз и используется для всех пакетов этого flow.
- **rte_security**: Библиотека DPDK для управления IPsec offload на уровне NIC (inline crypto). Интегрируется с ethdev для transparent IPsec processing.

---

### Теория

#### 1. Модели шифрования в DPDK

```
Модель 1: Inline crypto (NIC шифрует)
─────────────────────────────────────
Приложение → NIC → [AES-GCM в silicon] → Wire
                    ↑ Шифрование в NIC
                    ↑ 0 additional latency
                    ↑ 0 CPU overhead

Модель 2: Lookaside crypto (QAT шифрует)
─────────────────────────────────────────
Приложение → NIC → QAT → Wire
            ↑         ↑
            │ Шифрование в QAT
            │ DMA transfer NIC→QAT
            │ ~1-5 мкс additional latency

Модель 3: Software crypto (CPU шифрует)
───────────────────────────────────────
Приложение → CPU (AES-NI) → NIC → Wire
            ↑
            AES-NI инструкции
            ~5-20 мкс на пакет
            100% CPU overhead
```

**Сравнение моделей:**

| Модель | Latency | Throughput | CPU overhead | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **Inline (NIC)** | ~100 нс | Wire-speed | 0% | HFT, 5G UPF, real-time |
| **Lookaside (QAT)** | ~1-5 мкс | 50-100 Gbps | ~5-10% | General IPsec, VPN |
| **Software (AES-NI)** | ~5-20 мкс | 10-50 Gbps | ~30-50% | Development, low-throughput |

#### 2. Архитектура librte_cryptodev

```
┌──────────────────────────────────────────────┐
│ DPDK Application                             │
│ rte_crypto_op / rte_crypto_sym_session       │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ librte_cryptodev                             │
│ rte_crypto_sym_cryptooperation()            │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ PMD (crypto driver)                          │
│ dpdk_qat / dpdk_openssl / dpdk_aesni_mb    │
└──────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────────────────┐
│ Hardware (QAT / CPU AES-NI / NIC inline)     │
└──────────────────────────────────────────────┘
```

#### 3. IPsec Packet Format (ESP Tunnel Mode)

```
┌───────────────┬────────────┬──────────────┬───────────────┬──────┬─────────┐
│ Outer IP      │ ESP Header │ Inner IP     │ Inner Payload │ ESP  │ ESP     │
│ (src/dst)     │ (SPI,Seq)  │ (original)   │ (encrypted)   │ Auth │ Trailer │
│               │            │              │               │(HMAC)│(pad,Len)│
└───────────────┴────────────┴──────────────┴───────────────┴──────┴─────────┘
      20B          8B           20B            variable      12-16B  2-255B
```

**Поля ESP:**
- **SPI (Security Parameter Index)**: 32-битный идентификатор SA. Определяет алгоритм и ключ.
- **Sequence Number**: 32-битный счётник (防 replay attack).
- **IV (Initialization Vector)**: Для AES-GCM/CBC (обычно 8-16 байт).

---

### Практическое руководство

#### 1. Поиск crypto devices

```bash
# Просмотр всех crypto devices
./dpdk-devbind.py --crypto-devs
# → crypto_qat: 0000:00:04.0 (Intel QAT)
# → crypto_aesni_mb: software (AES-NI Multi-buffer)
# → crypto_openssl: software (OpenSSL)

# Или через testpmd:
# testpmd> show crypto capabilities 0
# → Symmetric crypto algorithms:
#   AES-CBC (128, 192, 256 bit keys)
#   AES-GCM (128, 192, 256 bit keys)
#   SHA-1, SHA-224, SHA-256, SHA-384, SHA-512
# → Asymmetric crypto algorithms:
#   RSA (1024, 2048, 4096 bit keys)
#   ECDSA (P-256, P-384, P-521)
```

#### 2. Создание crypto session (IPsec)

```c
#include <rte_cryptodev.h>
#include <rte_security.h>

// Создание crypto session
struct rte_cryptodev_sym_session *session;
session = rte_cryptodev_sym_session_create(
    crypto_dev_id,
    &crypto_sess_params,
    mempool
);

// Настройка IPsec session
struct rte_security_ipsec_xform ipsec_xform = {
    .spi = 0x1234,
    .seq = 0,
    .options = {
        .esn = 0,           // Extended Sequence Number
        .ecn = 0,           // ECT
    },
    .replay_win_sz = 1024, // Anti-replay window
    .direction = RTE_SECURITY_IPSEC_SA_DIR_EGRESS,  // TX
    .proto = RTE_SECURITY_IPSEC_SA_PROTO_ESP,
    .mode = RTE_SECURITY_IPSEC_SA_MODE_TUNNEL,  // Tunnel mode
};

// Настройка шифрования (AES-GCM 256)
struct rte_crypto_sym_xform cipher_xform = {
    .type = RTE_CRYPTO_SYM_XFORM_CIPHER,
    .cipher = {
        .op = RTE_CRYPTO_CIPHER_OP_ENCRYPT,
        .algo = RTE_CRYPTO_CIPHER_AES_GCM,
        .key.length = 32,  // 256 bit key
        .key.data = aes_key,
        .iv.length = 8,
    },
};

// Настройка аутентификации (GCM mode = integrated)
struct rte_crypto_sym_xform auth_xform = {
    .type = RTE_CRYPTO_SYM_XFORM_AUTH,
    .auth = {
        .op = RTE_CRYPTO_AUTH_OP_GENERATE,
        .algo = RTE_CRYPTO_AUTH_AES_GCM,
        .digest_length = 16,  // 128 bit
    },
};

// Цепочка xforms
cipher_xform.next = &auth_xform;
auth_xform.next = NULL;
```

#### 3. Обработка пакетов с IPsec

```c
// TX path: шифрование
struct rte_crypto_op *cop = rte_crypto_op_alloc(crypto_pool);
struct rte_mbuf *mbuf = ...;  // Исходный пакет

rte_crypto_sym_op_attach_mbuf(cop, mbuf);
cop->sym->m_src = mbuf;
cop->sym->cipher.data.length = rte_pktmbuf_pkt_len(mbuf);
cop->sym->cipher.data.offset = 0;

// Отправка в crypto device
rte_cryptodev_sym_enqueue_burst(crypto_dev_id, qp_id, &cop, 1);

// Получение зашифрованных пакетов
struct rte_crypto_op *results[1];
rte_cryptodev_sym_dequeue_burst(crypto_dev_id, qp_id, results, 1);

// Отправка зашифрованного пакета через NIC
rte_eth_tx_burst(port_id, txq, &mbuf, 1);
```

#### 4. Inline IPsec (NIC-based, Intel E810)

```c
// Включение inline IPsec на NIC
struct rte_security_ipsec_xform ipsec_xform = {
    .spi = 0x1234,
    .direction = RTE_SECURITY_IPSEC_SA_DIR_EGRESS,
    .proto = RTE_SECURITY_IPSEC_SA_PROTO_ESP,
    .mode = RTE_SECURITY_IPSEC_SA_MODE_TUNNEL,
};

struct rte_security_session_conf sess_conf = {
    .ipsec = ipsec_xform,
    .crypto_xform = &cipher_xform,
};

// Создание security session на NIC
struct rte_security_session *sec_sess = rte_security_session_create(
    security_ctx,
    &sess_conf,
    mempool
);

// Привязка security session к flow через rte_flow
struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_SECURITY,
      .conf = &(struct rte_flow_action_security){ .session = sec_sess } },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

rte_flow_create(port_id, &attr, pattern, actions, &error);
```

#### 5. Тестирование IPsec через ipsec-secgw

```bash
# Запуск DPDK ipsec-secgw (пример IPsec gateway)
./build/examples/ipsec-secgw -l 2-3 -n 4 -w 0000:01:00.0 \
  --socket-mem 1024,0 \
  -- \
  -p 0x3 \           # Порты: 0 и 1
  --rx="(0,0,0,0)" \ # RX на порту 0, queue 0
  --tx="(1,0)" \     # TX на порту 1
  --cryptodev=(0,0) \ # Crypto device 0, queue 0
  --sa "1" \         # Security Association
  --rule4 "1"        # IPv4 rule

# Тест с iperf3:
# Хост A (client): iperf3 -c 10.0.0.2
# Хост B (server): iperf3 -s
# На ipsec-secgw: трафик шифруется/дешифруется transparent
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| "No crypto devices found" | Crypto init fails | QAT не обнаружен или не bind к vfio-pci | `lspci \| grep QAT`; bind через dpdk-devbind |
| IPsec throughput низкий | < 10 Gbps | Software crypto вместо hardware | Используйте inline crypto или QAT |
| Replay attack detected | Пакеты отброшены | Sequence number не увеличивается | Проверьте sequence counter |
| `rte_cryptodev_sym_enqueue_burst` fails | 0 пакетов отправлено | Session не создана илиcipher 参数 неверны | Проверьте cipher algo, key length, IV |
| Inline crypto не работает | NIC не шифрует | Security session не привязан к flow | Проверьте rte_flow rule с action=security |

---

### Дополнительная информация

- **[DPDK: rte_flow API](dpdk_rte_flow.md)** — привязка security session к flow.
- **[DPDK: Тестирование](dpdk_testing.md)** — benchmarking IPsec throughput.
- **[DPDK: Архитектура PMD](dpdk_overview.md)** — как PMD работает с crypto.
- **[RFC 4303](https://tools.ietf.org/html/rfc4303)** — IPsec ESP standard.
- **[RFC 4106](https://tools.ietf.org/html/rfc4106)** — AES-GCM for IPsec.
- **[Intel QAT DPDK PMD](https://doc.dpdk.org/guides/cryptodevs/qat.html)** — документация по QAT.
- **[Intel E810 Inline IPsec](https://www.intel.com/content/www/us/en/products/details/processors/ethernet-networking/e810.html)** — inline crypto на E810.
