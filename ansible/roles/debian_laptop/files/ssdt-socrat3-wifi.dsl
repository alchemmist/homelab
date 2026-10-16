DefinitionBlock ("", "SSDT", 2, "HMLAB", "S3WIFI", 0x00000001)
{
    External (\PICM, IntObj)
    External (\_SB.PCI0.GPP1, DeviceObj)
    External (\_SB.LNKA, DeviceObj)
    External (\_SB.LNKB, DeviceObj)
    External (\_SB.LNKC, DeviceObj)
    External (\_SB.LNKD, DeviceObj)

    Scope (\_SB.PCI0.GPP1)
    {
        Method (_PRT, 0, NotSerialized)
        {
            If (\PICM)
            {
                Return (Package (0x04)
                {
                    Package (0x04) { 0xFFFF, Zero, Zero, 0x20 },
                    Package (0x04) { 0xFFFF, One, Zero, 0x21 },
                    Package (0x04) { 0xFFFF, 0x02, Zero, 0x22 },
                    Package (0x04) { 0xFFFF, 0x03, Zero, 0x23 }
                })
            }

            Return (Package (0x04)
            {
                Package (0x04) { 0xFFFF, Zero, \_SB.LNKA, Zero },
                Package (0x04) { 0xFFFF, One, \_SB.LNKB, Zero },
                Package (0x04) { 0xFFFF, 0x02, \_SB.LNKC, Zero },
                Package (0x04) { 0xFFFF, 0x03, \_SB.LNKD, Zero }
            })
        }
    }
}
