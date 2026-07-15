int validate(unsigned int b0, unsigned int b1, unsigned int b2) {
  return ((b0 + 1337) == 2007) && ((b0 ^ b1) == 1570) && 
    ((b2 % b1) == 870) && ((b2 / 2) == 22251); 
}