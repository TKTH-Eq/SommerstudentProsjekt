from neqsim.thermo import fluid, TPflash, printFrame

# Create a natural gas fluid
fl = fluid('srk')
fl.addComponent('methane', 0.85)
fl.addComponent('ethane', 0.10)
fl.addComponent('propane', 0.05)
fl.setTemperature(25.0, 'C')
fl.setPressure(60.0, 'bara')
fl.setMixingRule('classic')

TPflash(fl)
printFrame(fl)

print(f"Gas density:    {fl.getPhase('gas').getDensity('kg/m3'):.2f} kg/m3")
print(f"Gas viscosity:  {fl.getPhase('gas').getViscosity('kg/msec'):.6f} kg/(m*s)")
print(f"Z-factor:       {fl.getPhase('gas').getZ():.4f}")