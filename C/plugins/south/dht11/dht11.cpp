/*
 * FogLAMP south service plugin
 *
 * Copyright (c) 2018 OSIsoft, LLC
 *
 * Released under the Apache 2.0 Licence
 *
 * Author: Mark Riddoch
 */
#include <sstream>
#include <iostream>
#include <reading.h>
#include <wiringPi.h>
#include <dht11.h>
#include <logger.h>

using namespace std;

/**
 * Constructor for the random "sensor"
 */
DHT11::DHT11(unsigned int pin) :
m_pin(pin) // , m_initialDPValue(0), m_lastReading("initial", new Datapoint("dummy", m_initialDPValue))
{
	if ( wiringPiSetup() == -1 ) {
		Logger::getLogger()->fatal("wiringPiSetup failed, can't proceed");
		throw runtime_error("wiringPiSetup failed, can't proceed");
	}
	(void) takeReading(true);
}

/**
 * Destructor for the random "sensor"
 */
DHT11::~DHT11()
{
}

/**
 * Take a reading from the random "sensor"
 */
bool DHT11::readSensorData(uint8_t sensorData[])
{
        uint8_t laststate       = HIGH;
        uint8_t counter         = 0;
        uint8_t j               = 0, i;
        float   f; /* fahrenheit */
	uint8_t dht11_dat[5] = {0, 0, 0, 0, 0};

        /* pull pin down for 18 milliseconds */
        pinMode( m_pin, OUTPUT );
        digitalWrite( m_pin, LOW );
        delay( 18 );
        /* then pull it up for 40 microseconds */
        digitalWrite( m_pin, HIGH );
        delayMicroseconds( 40 );
        /* prepare to read the pin */
        pinMode( m_pin, INPUT );

        /* detect change and read data */
        for ( i = 0; i < MAXTIMINGS; i++ )
        {
                counter = 0;
                while ( digitalRead( m_pin ) == laststate )
                {
                        counter++;
                        delayMicroseconds( 1 );
                        if ( counter == 255 )
                        {
                                break;
                        }
                }
                laststate = digitalRead( m_pin );

                if ( counter == 255 )
                        break;

                /* ignore first 3 transitions */
                if ( (i >= 4) && (i % 2 == 0) )
                {
                        /* shove each bit into the storage bytes */
                        //dht11_dat[j / 8] <<= 1;
                        uint8_t num = j>>3;
                        dht11_dat[num] <<= 1;
                        if ( counter > 30 ) /* was 16 */
                                dht11_dat[num] |= 1;
                        j++;
                }
        }

        /*
         * check the read 40 bits (8bit x 5 ) + verify checksum in the last byte
         */
        if ( (j >= 40) &&
             (dht11_dat[4] == ( (dht11_dat[0] + dht11_dat[1] + dht11_dat[2] + dht11_dat[3]) & 0xFF) ) )
        {
		int k=0;
		for (k=0; k<4; k++)
			sensorData[k]=dht11_dat[k];
		return true;
        }else  {
                //Logger::getLogger()->info( "Data not good, skip\n" );
		return false;
        }
}


Reading DHT11::takeReading(bool firstReading)
{
	static uint8_t sensorData[4] = {0,0,0,0};
	
	bool valid = false;
	do {
		valid = readSensorData(sensorData);
	} while(!valid && firstReading);

        vector<Datapoint *> vec;

	stringstream tmp;
        tmp << ((unsigned int)sensorData[0]) << "." << ((unsigned int)sensorData[1]);
	DatapointValue dpv1(stod(tmp.str()));
        vec.push_back(new Datapoint("Humidity", dpv1));

	ostringstream tmp2;
        tmp2 << ((unsigned int)sensorData[2]) << "." <<  ((unsigned int)sensorData[3]);
	DatapointValue dpv2(stod(tmp2.str()));
        vec.push_back(new Datapoint ("Temperature", dpv2));

	return Reading("dht11", vec);
}

