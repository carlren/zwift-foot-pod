// Seeed's core ships this Nordic driver source but does not build it into core.a.
// Use the installed, pinned source rather than maintaining a separate I2C driver.
#include <nordic/nrfx/drivers/src/nrfx_twim.c>
