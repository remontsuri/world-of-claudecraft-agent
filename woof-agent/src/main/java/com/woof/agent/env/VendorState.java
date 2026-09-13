package com.woof.agent.env;

import com.fasterxml.jackson.annotation.JsonProperty;

/** Vendor state */
public class VendorState {
    public boolean open;
    public java.util.List<VendorItem> items;
    public String vendorName;
    public double x, y, z;

    public VendorState() {}
}
