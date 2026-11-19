"""Words in a question that send it to the status tool that can answer it, in Kiboto's five languages.

The first router knew English only, so "Wie viel Speicherplatz ist frei?" reached the model with
no reading to answer from. A word here costs one extra reading in the answer's context when it
matches by accident, so words that mean something else in another of the languages stay out:
Spanish "red" (network) is the English colour, "disco" is also music, "memoria" is also a thesis.
Chinese is matched anywhere in the sentence (it has no spaces); the rest as whole words."""

STORAGE_WORDS = (
    "storage pool",
    "storage pools",
    "zpool",
    "pools",
    "pool status",
    "array status",
    "storage status",
    "storage capacity",
    "how much storage",
    "free space",
    "usable space",
    "disk space",
    "btrfs raid",
    "zfs pool",
    "damaged file",
    "damaged files",
    "corrupted file",
    "corrupted files",
    "corrupt files",
    # German
    "speicherplatz",
    "freier speicher",
    "speicherpool",
    "speicherpools",
    "beschädigte datei",
    "beschädigte dateien",
    # Spanish
    "espacio libre",
    "espacio disponible",
    "espacio en disco",
    "espacio de almacenamiento",
    "archivo dañado",
    "archivos dañados",
    # French
    "espace libre",
    "espace disponible",
    "espace disque",
    "espace de stockage",
    "fichier endommagé",
    "fichiers endommagés",
    # Chinese
    "可用空间",
    "剩余空间",
    "存储空间",
    "磁盘空间",
    "存储池",
    "损坏的文件",
    "文件损坏",
)

TELEMETRY_WORDS = (
    "cpu",
    "ram",
    "memory",
    "npu",
    "gpu",
    "hardware",
    "telemetry",
    "uptime",
    "system load",
    "system status",
    "electricity",
    "kwh",
    "watts",
    "power use",
    "power usage",
    "power draw",
    "power consumption",
    "energy use",
    "energy usage",
    "been up",
    "been running",
    # German
    "laufzeit",
    "betriebszeit",
    "prozessor",
    "arbeitsspeicher",
    "auslastung",
    "stromverbrauch",
    # Spanish
    "procesador",
    "electricidad",
    "consumo eléctrico",
    "consumo electrico",
    "consumo de energía",
    "consumo de energia",
    "lleva encendido",
    "tiempo encendido",
    # French
    "temps de fonctionnement",
    "processeur",
    "mémoire vive",
    "électricité",
    "consommation électrique",
    "consommation d'énergie",
    # Chinese
    "处理器",
    "内存",
    "耗电",
    "用电",
    "运行时间",
    "开机多久",
)

DISK_WORDS = (
    "disk",
    "disks",
    "drive",
    "drives",
    "hdd",
    "nvme",
    "standby",
    "sleeping",
    "spun down",
    "spinup",
    "smart",
    "drive health",
    "disk health",
    # German
    "festplatte",
    "festplatten",
    "laufwerk",
    "laufwerke",
    # Spanish
    "disco duro",
    "discos duros",
    "los discos",
    "mis discos",
    # French
    "disque",
    "disques",
    # Chinese
    "硬盘",
    "磁盘",
)

FAN_WORDS = (
    "fan",
    "fans",
    "rpm",
    "pwm",
    "cooling",
    "thermal",
    "zero rpm",
    "acoustic",
    # German
    "lüfter",
    "luefter",
    "kühlung",
    # Spanish
    "ventilador",
    "ventiladores",
    # French
    "ventilateur",
    "ventilateurs",
    # Chinese
    "风扇",
    "散热",
)

APP_WORDS = (
    "docker",
    "dockers",
    "container",
    "containers",
    "running apps",
    "services",
    "sonarr",
    "radarr",
    "immich",
    "plex",
    # German ("Container" is the same word)
    "laufende apps",
    "apps laufen",
    # Spanish
    "contenedor",
    "contenedores",
    "aplicaciones en ejecución",
    # French
    "conteneur",
    "conteneurs",
    "applications en cours",
    # Chinese
    "容器",
    "正在运行的应用",
    "运行中的应用",
)

NETWORK_WORDS = (
    "network",
    "interfaces",
    "ip address",
    "my ip",
    "ethernet",
    "lan",
    "gateway",
    "default gateway",
    "dns",
    "link speed",
    "subnet",
    "network card",
    "hostname",
    # German
    "netzwerk",
    "ip-adresse",
    "ip adresse",
    # Spanish
    "dirección ip",
    "direccion ip",
    "puerta de enlace",
    # French
    "réseau",
    "adresse ip",
    "passerelle",
    # Chinese
    "ip地址",
    "主机名",
    "网关",
    "网速",
    "网络状态",
    "网络连接",
)
