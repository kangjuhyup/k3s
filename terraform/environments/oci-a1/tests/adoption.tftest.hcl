# Provider API operations are mocked; no OCI credentials or SSH are used.
mock_provider "oci" {}

# Terraform requires an explicit resource override for import declarations.
# Only provider-computed fields are substituted; input mappings and lifecycle
# checks are still evaluated from the real configuration.
override_resource {
  target = oci_core_instance.nodes
}

variables {
  oci_region        = "us-ashburn-1" # Synthetic test context, not the user's region.
  adoption_reviewed = true
  nodes = {
    node01 = {
      existing_instance_ocid = "ocid1.instance.oc1.iad.testnode01"
      compartment_id         = "ocid1.compartment.oc1..testcompartment"
      availability_domain    = "TEST:US-ASHBURN-AD-1"
      display_name           = "existing-a1"
      role                   = "server"
      ocpus                  = 4
      memory_in_gbs          = 24
      subnet_id              = "ocid1.subnet.oc1.iad.testsubnet"
      assign_public_ip       = true
      source_type            = "image"
      source_id              = "ocid1.image.oc1.iad.testimage"
    }
  }
}

run "existing_server" {
  command = plan

  assert {
    condition = (
      oci_core_instance.nodes["node01"].shape == "VM.Standard.A1.Flex" &&
      oci_core_instance.nodes["node01"].shape_config[0].ocpus == 4 &&
      oci_core_instance.nodes["node01"].shape_config[0].memory_in_gbs == 24 &&
      output.nodes["node01"].role == "server"
    )
    error_message = "The existing server's A1 sizing and inventory role must be preserved."
  }

  assert {
    condition = toset(keys(output.nodes["node01"])) == toset([
      "instance_ocid", "role", "private_ip", "public_ip"
    ])
    error_message = "Inventory output must not contain metadata, tokens or entire resources."
  }
}

run "reject_unreviewed_adoption" {
  command = plan

  variables {
    adoption_reviewed = false
  }

  expect_failures = [oci_core_instance.nodes["node01"]]
}

run "reject_invalid_role" {
  command = plan

  variables {
    adoption_reviewed = true
    nodes = {
      node01 = merge(var.nodes.node01, { role = "worker" })
    }
  }

  expect_failures = [var.nodes]
}

run "reject_duplicate_instance" {
  command = plan

  variables {
    adoption_reviewed = true
    nodes = {
      node01 = var.nodes.node01
      node02 = merge(var.nodes.node01, { role = "agent" })
    }
  }

  expect_failures = [var.nodes]
}

run "reject_placeholder_id" {
  command = plan

  variables {
    nodes = {
      node01 = merge(var.nodes.node01, { existing_instance_ocid = "REPLACE_WITH_EXISTING_INSTANCE_OCID" })
    }
  }

  expect_failures = [var.nodes]
}

run "reject_wrong_source_type" {
  command = plan

  variables {
    nodes = {
      node01 = merge(var.nodes.node01, { source_type = "bootVolume" })
    }
  }

  expect_failures = [var.nodes]
}

run "reject_invalid_sizing" {
  command = plan

  variables {
    nodes = {
      node01 = merge(var.nodes.node01, { ocpus = 0 })
    }
  }

  expect_failures = [var.nodes]
}

run "reject_null_node" {
  command = plan

  variables {
    nodes = { node01 = null }
  }

  expect_failures = [var.nodes]
}

run "reject_null_role" {
  command = plan

  variables {
    nodes = {
      node01 = merge(var.nodes.node01, { role = null })
    }
  }

  expect_failures = [var.nodes]
}

run "additional_existing_agent_keeps_server_identity" {
  command = plan

  variables {
    nodes = {
      node01 = var.nodes.node01
      node02 = merge(var.nodes.node01, {
        existing_instance_ocid = "ocid1.instance.oc1.iad.testnode02"
        display_name           = "existing-agent"
        role                   = "agent"
        ocpus                  = 1
        memory_in_gbs          = 6
        assign_public_ip       = false
      })
    }
    metadata_by_node = { node01 = { fixture = "synthetic-test-value" } }
  }

  assert {
    condition = (
      toset(keys(output.nodes)) == toset(["node01", "node02"]) &&
      output.nodes.node01.role == "server" &&
      output.nodes.node02.role == "agent" &&
      oci_core_instance.nodes["node01"].shape_config[0].ocpus == 4 &&
      oci_core_instance.nodes["node02"].shape_config[0].ocpus == 1 &&
      oci_core_instance.nodes["node02"].create_vnic_details[0].assign_public_ip == "false"
    )
    error_message = "Adding an existing agent must keep the server's identity/sizing and respect each node's public-IP setting."
  }

  assert {
    condition     = !issensitive(output.nodes)
    error_message = "Sensitive metadata must not flow into inventory output."
  }
}

run "accept_root_compartment" {
  command = plan

  variables {
    nodes = {
      node01 = merge(var.nodes.node01, { compartment_id = "ocid1.tenancy.oc1..testtenancy" })
    }
  }

  assert {
    condition     = oci_core_instance.nodes["node01"].compartment_id == "ocid1.tenancy.oc1..testtenancy"
    error_message = "OCI root compartment uses the tenancy OCID and must be supported."
  }
}
