FROM debian:trixie
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        live-build debootstrap squashfs-tools xorriso mtools dosfstools \
        grub-pc-bin grub-efi-amd64-bin grub-efi-ia32-bin syslinux isolinux \
        ca-certificates cpio rsync wget \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
CMD ["bash", "iso/build.sh"]
