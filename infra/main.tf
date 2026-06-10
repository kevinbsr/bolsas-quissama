terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.66.0"
    }
  }
}

variable "proxmox_api_token" {
  description = "Token de API do Proxmox"
  type        = string
  sensitive   = true
}

provider "proxmox" {
  endpoint  = "https://192.168.3.200:8006/"
  api_token = var.proxmox_api_token
  insecure  = true
}

resource "proxmox_virtual_environment_file" "debian_template" {
  content_type = "vztmpl"
  datastore_id = "local"
  node_name    = "ragnar"

  source_file {
    path = "http://download.proxmox.com/images/system/debian-12-standard_12.12-1_amd64.tar.zst"
  }
}

resource "proxmox_virtual_environment_container" "scraper_lxc" {
  description = "LXC para automacao do Playwright - Gerenciado via Terraform"
  node_name   = "ragnar"
  vm_id       = 102

  initialization {
    hostname = "scraper-bolsas"

    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }

    user_account {
      keys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGcseBMyFVw0DBaf91HQoR5OIqcR458sAb7cg8WrXcla kb.kevinbenevides@gmail.com"
      ]
    }
  }

  network_interface {
    name   = "veth0"
    bridge = "vmbr0"
  }

  cpu {
    cores = 2
  }

  memory {
    dedicated = 4096
  }

  disk {
    datastore_id = "local-lvm"
    size         = 8
  }

  operating_system {
    template_file_id = proxmox_virtual_environment_file.debian_template.id
    type             = "debian"
  }

  unprivileged  = true
  start_on_boot = true
}
