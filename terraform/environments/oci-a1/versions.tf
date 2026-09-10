terraform {
  required_version = "= 1.16.1"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 9.0.0"
    }
  }

  # Single-operator bootstrap state lives outside tracked configuration.
  # Wasabi is for workload backups, not the Terraform backend.
  backend "local" {
    path = "../../../.local/terraform/oci-a1/terraform.tfstate"
  }
}
